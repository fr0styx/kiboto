/**
 * One row per app (Apps decision 2). Without the Docker details, the containers of one Compose
 * project are one app: one row, one state, one Open, and a menu that starts, stops, updates,
 * backs up and removes the whole app. The server does those as one (backend/services/whole_app.py).
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast, showConfirmToast } from '../toast.js';
import { conditionOf } from './app-condition.js';
import { followJob } from './stack-apply.js';

// worst first: an app is as well as its worst part
const WORST = [
  'crashed',
  'dead',
  'restarting',
  'unhealthy',
  'starting',
  'removing',
  'paused',
  'created',
  'stopped',
  'unknown',
];
const UP = ['running', 'starting', 'unhealthy'];

export const isAppRow = (c) => Boolean(c && c.__app);

/** The app a stack's parts make: one item the table draws like an app of its own. */
export function appOf(stack, parts) {
  const conds = parts.map(conditionOf);
  const up = conds.filter((c) => UP.includes(c)).length;
  let condition = 'running';
  const bad = WORST.slice(0, 4).find((w) => conds.includes(w));
  if (bad) condition = bad;
  else if (up === 0) condition = WORST.find((w) => conds.includes(w)) || 'stopped';
  else if (conds.includes('starting')) condition = 'starting';
  else if (conds.includes('unhealthy')) condition = 'unhealthy';
  const worstPart = parts.find((p) => conditionOf(p) === condition) || parts[0];
  const withPage = parts.find((p) => p.webui_url && p.state === 'running') || parts.find((p) => p.webui_url);
  const status =
    up && up < parts.length
      ? t('approw.some_run', '{running} of {total, plural, one {# part} other {# parts}} running.', {
          running: up,
          total: parts.length,
        })
      : t('approw.parts', '{count, plural, one {# part} other {# parts}}', { count: parts.length });
  return {
    __app: true,
    id: `app:${stack}`,
    name: stack,
    stack,
    parts,
    condition,
    state: UP.includes(condition) ? 'running' : condition === 'paused' ? 'paused' : 'exited',
    reason: worstPart.reason,
    exit_code: worstPart.exit_code,
    restart_count: worstPart.restart_count,
    status,
    image: parts
      .map((p) => p.image)
      .filter(Boolean)
      .join(', '),
    webui_url: withPage?.webui_url || '',
    primary_port: withPage?.primary_port || 0,
    ports: [],
    hardware_badges: parts.flatMap((p) => p.hardware_badges || []),
    managed_by: 'compose',
    kiboto_own: parts.some((p) => p.kiboto_own),
  };
}

/** The list with each stack's containers folded into one app, in the order given; apps on their own stay. */
export function mergeApps(list) {
  const byStack = new Map();
  for (const c of list) {
    if (c && c.stack) {
      if (!byStack.has(c.stack)) byStack.set(c.stack, []);
      byStack.get(c.stack).push(c);
    }
  }
  const out = [];
  const placed = new Set();
  for (const c of list) {
    if (!c || !c.stack) {
      out.push(c);
    } else if (!placed.has(c.stack)) {
      placed.add(c.stack);
      out.push(appOf(c.stack, byStack.get(c.stack)));
    }
  }
  return out;
}

/** Whether any part of an app has a newer image, from the update check's cache. */
export function appUpdateInfo(app, cache) {
  const known = cache?.containers || {};
  const has = app.parts.some((p) => (known[p.name] || known[p.id])?.has_update);
  return { has_update: has };
}

/** The ids of the containers behind a list of rows (app rows stand for their parts). */
export function partIds(rows) {
  return rows.flatMap((c) => (isAppRow(c) ? c.parts.map((p) => p.id) : [c.id])).filter(Boolean);
}

/**
 * The "..." menu of an app row.
 * @param {any} app
 * @param {boolean} hasUpdate
 * @param {(action: string) => unknown} run
 * @param {(part: any) => unknown} openPart
 */
export function appMenu(app, hasUpdate, run, openPart) {
  const items = [];
  if (app.condition === 'paused')
    items.push({ icon: '▶', label: t('appmenu.resume', 'Resume'), onClick: () => run('unpause') });
  else if (UP.includes(app.condition) || app.condition === 'restarting') {
    items.push({ icon: '🔄', label: t('appmenu.restart', 'Restart'), onClick: () => run('restart') });
    items.push({ icon: '⏹', label: t('appmenu.stop', 'Stop'), onClick: () => run('stop') });
  } else items.push({ icon: '▶', label: t('appmenu.start', 'Start'), onClick: () => run('start') });
  if (hasUpdate) items.push({ icon: '⬆️', label: t('appmenu.update', 'Update'), onClick: () => run('update') });
  items.push({ icon: '💾', label: t('appmenu.backup', 'Back up now'), onClick: () => run('backup') });
  for (const part of app.parts) {
    items.push({
      icon: '🔍',
      label: t('approw.part', 'Part: {name}', { name: part.service || part.name }),
      onClick: () => openPart(part),
    });
  }
  items.push({ icon: '🗑️', label: t('appmenu.remove', 'Remove'), destructive: true, onClick: () => run('remove') });
  return items;
}

/** What a finished start, stop, restart or resume says. */
export function doneSaid(action, name) {
  if (action === 'start') return t('approw.done_start', '{name} started.', { name });
  if (action === 'stop') return t('approw.done_stop', '{name} stopped.', { name });
  if (action === 'restart') return t('approw.done_restart', '{name} restarted.', { name });
  return t('approw.done_unpause', '{name} resumed.', { name });
}

/**
 * Does one action on a whole app and says how it went.
 * @param {any} app
 * @param {string} action start | stop | restart | unpause | update | backup | remove
 * @param {{ reload?: () => unknown, follow?: typeof followJob }} [opts]
 */
export async function runAppAction(app, action, opts = {}) {
  const reload = opts.reload || (() => {});
  const follow = opts.follow || followJob;
  const name = app.name;
  const enc = encodeURIComponent(app.stack);
  try {
    if (action === 'backup') {
      showToast(t('approw.backing_up', 'Backing up {name}…', { name }), 'info');
      const res = await api.post(`/api/docker/stacks/${enc}/backup`);
      const b = res?.backup || {};
      showToast(
        t('approw.backed_up', '{name} is backed up ({file}).', {
          name,
          file: b.size_human ? `${b.filename}, ${b.size_human}` : b.filename || '',
        }),
        'success'
      );
      return true;
    }
    if (action === 'update') {
      const res = await api.post(`/api/docker/stacks/${enc}/update`);
      if (res?.status === 'up_to_date') {
        showToast(t('approw.up_to_date', '{name} is up to date.', { name }), 'info');
        return true;
      }
      showToast(
        t('approw.updating', 'Updating {name}: {parts}…', { name, parts: (res?.parts || []).join(', ') }),
        'info'
      );
      const end = await follow(res.job);
      if (end.status === 'done') showToast(t('approw.updated', '{name} is updated.', { name }), 'success');
      else showToast(end.error || t('approw.update_failed', '{name} was not updated.', { name }), 'error');
      await reload();
      return end.status === 'done';
    }
    if (action === 'remove') {
      const res = await api.delete(`/api/docker/stacks/${enc}`);
      if (res?.success) {
        showToast(t('approw.removed', '{name} is removed. A backup of it was kept.', { name }), 'success');
      } else {
        const left = (res?.failed || []).map((f) => f.name).join(', ');
        showToast(
          t('approw.remove_partly', 'Some parts of {name} were not removed: {parts}', { name, parts: left }),
          'error'
        );
      }
      await reload();
      return Boolean(res?.success);
    }
    if (action === 'unpause') {
      for (const p of app.parts.filter((x) => conditionOf(x) === 'paused')) {
        await api.post(`/api/docker/containers/${encodeURIComponent(p.id)}/action`, { action: 'unpause' });
      }
    } else {
      await api.post(`/api/docker/stacks/${enc}/action`, { action });
    }
    showToast(doneSaid(action, name), 'success');
    await reload();
    return true;
  } catch (err) {
    if (/** @type {any} */ (err)?.error === 'cancelled') return false;
    showToast(t('approw.failed', '{name}: {error}', { name, error: /** @type {Error} */ (err).message }), 'error');
    return false;
  }
}

/** Asks before an update, then runs it. */
export function askAppUpdate(app, reload) {
  showConfirmToast(
    t('approw.update_title', 'Update “{name}”?', { name: app.name }),
    t(
      'approw.update_msg',
      'Each part with a newer version is updated, one after the other; folders and settings stay as they are.'
    ),
    () => runAppAction(app, 'update', { reload })
  );
}
