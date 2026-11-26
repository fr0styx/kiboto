// Replace a drive: the pool's own tool rebuilds onto an empty drive, chosen in a small dialog.
import { describe, it, expect, vi, beforeEach } from 'vitest';

let plans;
const posts = [];
let refuse = null;
vi.mock('../api.js', () => ({
  api: {
    get: async () => (plans.length > 1 ? plans.shift() : plans[0]),
    post: async (url, body) => {
      posts.push([url, body]);
      if (refuse) throw refuse;
      return { started: true };
    },
  },
}));

const { openDriveReplace, bodyHtml, whyNot, progressText } = await import('../components/drive-replace.js');
const { replaceButtonHtml } = await import('../components/chassis-visualizer.js');

const PLAN = {
  pool: 'tank',
  fs: 'zfs',
  can: true,
  why: '',
  members: [
    { id: '/dev/disk/by-id/virtio-A-part1', label: '/dev/disk/by-id/virtio-A-part1', state: 'ONLINE', size_bytes: 8e9 },
    { id: '1234', label: '/dev/disk/by-id/virtio-B-part1', state: 'UNAVAIL', size_bytes: 0 },
  ],
  drives: [{ dev: 'vdg', path: '/dev/vdg', size_bytes: 8e9, serial: 'KBTESTDISK6', model: 'Disk' }],
  progress: { running: false, percent: null },
};

beforeEach(() => {
  posts.length = 0;
  refuse = null;
  document.body.innerHTML = '';
});

describe('Replace a drive', () => {
  it('picks the missing drive and the first empty one', () => {
    document.body.innerHTML = bodyHtml(PLAN);
    const old = /** @type {HTMLInputElement} */ (document.querySelector('input[name="dr-old"]:checked'));
    expect(old.value).toBe('1234');
    expect(document.body.textContent).toContain('UNAVAIL');
    expect(/** @type {HTMLInputElement} */ (document.querySelector('input[name="dr-new"]:checked')).value).toBe(
      '/dev/vdg'
    );
  });

  it('says why a pool cannot rebuild, and when no drive fits', () => {
    expect(whyNot('no_copy')).toContain('no second copy');
    expect(whyNot('one_drive')).toContain('one drive');
    expect(whyNot('no_status')).toContain('cannot read');
    document.body.innerHTML = bodyHtml({ ...PLAN, drives: [] });
    expect(document.body.textContent).toContain('No empty drive large enough');
    expect(progressText({ running: true, percent: 25.47 })).toContain('25% done');
    expect(progressText({ running: true, percent: null })).toContain('Rebuilding.');
    expect(progressText({ running: false })).toBe('');
  });

  it('starts the rebuild with the chosen drives and then shows how far it is', async () => {
    plans = [PLAN, { ...PLAN, progress: { running: true, percent: 3 } }];
    const done = vi.fn();
    const dlg = await openDriveReplace('tank', 'tank', done);
    dlg.querySelector('#dr-start').click();
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
    expect(posts).toEqual([['/api/storage/pools/tank/replace', { old: '1234', new: '/dev/vdg' }]]);
    expect(done).toHaveBeenCalled();
    expect(dlg.querySelector('#dr-progress').textContent).toContain('3% done');
    expect(dlg.querySelector('#dr-start')).toBeNull(); // no second start while it rebuilds
    dlg.querySelector('[data-dr-close]').click();
    expect(document.getElementById('drive-replace-dialog')).toBeNull();
  });

  it('shows a refusal and lets the person try again; a cancelled confirmation says nothing', async () => {
    plans = [PLAN];
    refuse = new Error('That drive is not an empty drive large enough for this pool.');
    const dlg = await openDriveReplace('tank');
    dlg.querySelector('#dr-start').click();
    await new Promise((r) => setTimeout(r, 0));
    expect(dlg.querySelector('#dr-error').hidden).toBe(false);
    expect(dlg.querySelector('#dr-start').disabled).toBe(false);
    refuse = { error: 'cancelled' };
    dlg.querySelector('#dr-error').hidden = true;
    dlg.querySelector('#dr-start').click();
    await new Promise((r) => setTimeout(r, 0));
    expect(dlg.querySelector('#dr-error').hidden).toBe(true);
  });

  it('says when the feature table still has drive replacement as being checked here', async () => {
    plans = [{ ...PLAN, edition: 'check' }];
    let dlg = await openDriveReplace('tank');
    expect(dlg.querySelector('.dr-edition').textContent).toBe('Built for this edition, and still being checked.');
    plans = [{ ...PLAN, edition: 'yes' }];
    dlg = await openDriveReplace('tank');
    expect(dlg.querySelector('.dr-edition')).toBeNull();
  });

  it('a pool that cannot rebuild offers no start', async () => {
    plans = [{ ...PLAN, can: false, why: 'no_copy', drives: [] }];
    const dlg = await openDriveReplace('fast');
    expect(dlg.querySelector('#dr-start')).toBeNull();
    expect(dlg.textContent).toContain('no second copy');
  });

  it('is offered on a pool the server says can be replaced', () => {
    expect(replaceButtonHtml({ id: 'tank', name: 'tank', replaceable: true })).toContain('data-pool-id="tank"');
    expect(replaceButtonHtml({ id: 'tank', replaceable: false })).toBe('');
    expect(replaceButtonHtml(null)).toBe('');
  });
});
