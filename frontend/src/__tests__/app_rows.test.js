// Apps decision 2: without the Docker details, the containers of one Compose project are one app.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const calls = [];
let answers = {};
vi.mock('../api.js', () => {
  const reply = (method) => async (url, body) => {
    calls.push([method, url, body]);
    const a = answers[`${method} ${url}`];
    if (a instanceof Error) throw a;
    return a ?? {};
  };
  return { api: { get: reply('GET'), post: reply('POST'), delete: reply('DELETE') } };
});
const toasts = [];
const confirms = [];
vi.mock('../toast.js', () => ({
  showToast: (msg, kind) => toasts.push([msg, kind]),
  showConfirmToast: (title, msg, ok) => confirms.push([title, msg, ok]),
  showBottomSheet: () => {},
}));

const { appOf, mergeApps, appUpdateInfo, partIds, appMenu, runAppAction, doneSaid, askAppUpdate, isAppRow } = await import('../components/app-rows.js');

const part = (name, state, extra = {}) => ({ id: `id-${name}`, name, stack: 'immich', state, status: state === 'running' ? 'Up' : 'Exited (0)', ports: [], ...extra });

beforeEach(() => {
  calls.length = 0;
  toasts.length = 0;
  confirms.length = 0;
  answers = {};
});

describe('one row per app', () => {
  it('folds a stack into one app and leaves apps on their own', () => {
    const list = [part('db', 'running'), part('web', 'running', { webui_url: 'http://[HOST]:2283', primary_port: 2283 }), { id: 'j', name: 'jellyfin', state: 'running' }];
    const rows = mergeApps(list);
    expect(rows.map((r) => r.name)).toEqual(['immich', 'jellyfin']);
    const app = rows[0];
    expect(isAppRow(app) && app.id).toBe('app:immich');
    expect(app.parts.length).toBe(2);
    expect(app.condition).toBe('running');
    expect(app.webui_url).toBe('http://[HOST]:2283');
    expect(app.status).toBe('2 parts');
    expect(isAppRow(rows[1])).toBe(false);
  });

  it('is as well as its worst part', () => {
    expect(appOf('s', [part('a', 'running'), part('b', 'exited')]).status).toBe('1 of 2 parts running.');
    expect(appOf('s', [part('a', 'running'), part('b', 'exited')]).state).toBe('running');
    expect(appOf('s', [part('a', 'running'), part('b', 'exited', { condition: 'crashed', exit_code: 1 })]).condition).toBe('crashed');
    expect(appOf('s', [part('a', 'exited'), part('b', 'paused')]).condition).toBe('paused');
    expect(appOf('s', [part('a', 'exited'), part('b', 'paused')]).state).toBe('paused');
    expect(appOf('s', [part('a', 'exited'), part('b', 'exited')]).state).toBe('exited');
    expect(appOf('s', [part('a', 'running', { condition: 'starting' }), part('b', 'running')]).condition).toBe('starting');
    expect(appOf('s', [part('a', 'running', { condition: 'unhealthy' }), part('b', 'running')]).condition).toBe('unhealthy');
    expect(appOf('s', [part('a', 'running', { condition: 'unhealthy' })]).status).toBe('1 part');
  });

  it('has an update when any part has one, and stands for its parts in a selection', () => {
    const app = appOf('immich', [part('db', 'running'), part('web', 'running')]);
    expect(appUpdateInfo(app, { containers: { web: { has_update: true } } }).has_update).toBe(true);
    expect(appUpdateInfo(app, null).has_update).toBe(false);
    expect(partIds([app, { id: 'j' }])).toEqual(['id-db', 'id-web', 'j']);
  });

  it('its menu acts on the whole app and lists its parts', () => {
    const run = vi.fn();
    const openPart = vi.fn();
    const up = appMenu(appOf('immich', [part('db', 'running', { service: 'database' })]), true, run, openPart);
    expect(up.map((i) => i.label)).toEqual(['Restart', 'Stop', 'Update', 'Back up now', 'Part: database', 'Remove']);
    up.forEach((i) => i.onClick());
    expect(run.mock.calls.map((c) => c[0])).toEqual(['restart', 'stop', 'update', 'backup', 'remove']);
    expect(openPart).toHaveBeenCalledTimes(1);
    const down = appMenu(appOf('s', [part('a', 'exited')]), false, run, openPart);
    expect(down[0].label).toBe('Start');
    down[0].onClick();
    const paused = appMenu(appOf('s', [part('a', 'paused')]), false, run, openPart);
    expect(paused[0].label).toBe('Resume');
    paused[0].onClick();
    expect(run.mock.calls.slice(-2).map((c) => c[0])).toEqual(['start', 'unpause']);
  });
});

describe('whole-app actions', () => {
  const app = appOf('immich', [part('db', 'running'), part('web', 'paused')]);

  it('start, stop, restart and resume', async () => {
    const reload = vi.fn();
    expect(await runAppAction(app, 'restart', { reload })).toBe(true);
    expect(calls.at(-1)).toEqual(['POST', '/api/docker/stacks/immich/action', { action: 'restart' }]);
    expect(toasts.at(-1)).toEqual(['immich restarted.', 'success']);
    await runAppAction(app, 'unpause', { reload });
    expect(calls.at(-1)).toEqual(['POST', '/api/docker/containers/id-web/action', { action: 'unpause' }]);
    expect(reload).toHaveBeenCalledTimes(2);
    expect(doneSaid('start', 'x')).toBe('x started.');
    expect(doneSaid('stop', 'x')).toBe('x stopped.');
  });

  it('backs up the whole app as one archive', async () => {
    answers['POST /api/docker/stacks/immich/backup'] = { backup: { filename: 'immich_on-demand.tar.gz', size_human: '3 MB' } };
    await runAppAction(app, 'backup');
    expect(toasts.at(-1)).toEqual(['immich is backed up (immich_on-demand.tar.gz, 3 MB).', 'success']);
  });

  it('updates part by part and follows the job', async () => {
    answers['POST /api/docker/stacks/immich/update'] = { status: 'started', job: 'job:1', parts: ['db', 'web'] };
    const follow = vi.fn(async () => ({ status: 'done', error: '' }));
    expect(await runAppAction(app, 'update', { follow })).toBe(true);
    expect(follow).toHaveBeenCalledWith('job:1');
    expect(toasts.map((x) => x[0])).toEqual(['Updating immich: db, web…', 'immich is updated.']);
    toasts.length = 0;
    expect(await runAppAction(app, 'update', { follow: async () => ({ status: 'error', error: 'web could not be updated: pull failed' }) })).toBe(false);
    expect(toasts.at(-1)).toEqual(['web could not be updated: pull failed', 'error']);
    answers['POST /api/docker/stacks/immich/update'] = { status: 'up_to_date', parts: [] };
    await runAppAction(app, 'update');
    expect(toasts.at(-1)).toEqual(['immich is up to date.', 'info']);
    askAppUpdate(app, () => {});
    expect(confirms[0][0]).toBe('Update “immich”?');
    await confirms[0][2]();
  });

  it('removes the whole app, says what stayed, and is quiet when cancelled', async () => {
    answers['DELETE /api/docker/stacks/immich'] = { success: true };
    expect(await runAppAction(app, 'remove')).toBe(true);
    expect(toasts.at(-1)).toEqual(['immich is removed. A backup of it was kept.', 'success']);
    answers['DELETE /api/docker/stacks/immich'] = { success: false, failed: [{ name: 'web', error: 'busy' }] };
    expect(await runAppAction(app, 'remove')).toBe(false);
    expect(toasts.at(-1)).toEqual(['Some parts of immich were not removed: web', 'error']);
    toasts.length = 0;
    answers['DELETE /api/docker/stacks/immich'] = Object.assign(new Error('Cancelled'), { error: 'cancelled' });
    expect(await runAppAction(app, 'remove')).toBe(false);
    expect(toasts).toEqual([]);
    answers['POST /api/docker/stacks/immich/action'] = new Error('No containers found');
    await runAppAction(app, 'stop');
    expect(toasts.at(-1)).toEqual(['immich: No containers found', 'error']);
  });
});
