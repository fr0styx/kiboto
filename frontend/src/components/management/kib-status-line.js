// Kib's status line (SET-26, AI 4; report section 4, "Status line"): the first thing on Kib's
// settings. One line with an icon and words, a second line, and the one button that fits. It takes
// the place of the five ribbon pills (hardware tier, model, "Standby Guard", counters, sync state),
// so "is Kib ready, and what can it read" is answered without reading the rest of the page.
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { formatNumber } from '../../format.js';

/**
 * Which state Kib is in, from the status the server sends (GET /api/ai/status), in the order the
 * report gives: a state further down only shows when none above it applies.
 * @param {any} res
 * @returns {{ key: string, icon: string, title: string, second: string, act: string, label: string }}
 */
export function kibState(res = {}) {
  const sync = res.sync_progress || {};
  const learn = res.learning_results || {};
  const guard = res.standby_guard || {};
  const folders = Array.isArray(res.watched_paths) ? res.watched_paths.length : 0;
  const files = Number(res.indexed_count ?? res.index_stats?.total_files ?? 0) || 0;
  const state = String(sync.state || res.sync_state || 'idle').toLowerCase();
  const none = { act: '', label: '' };

  if (res.enabled === false) {
    return { key: 'off', icon: '○', title: t('kibs.off', 'Kib is off'), second: t('kibs.off_2', 'Kib does not read your files. Chat and search answer from what it already knows.'), act: 'on', label: t('kibs.turn_on', 'Turn on') };
  }
  if (state === 'running') {
    const done = Number(sync.indexed_files || 0) + Number(sync.skipped_unchanged || 0);
    const total = Number(sync.total_files || 0);
    // the total is what the index knew of these folders last time: "about", and only while it holds
    const title = total > 0 && done <= total
      ? t('kibs.reading_of', 'Kib is reading your files: {done} of about {total}', { done: formatNumber(done), total: formatNumber(total) })
      : t('kibs.reading_so_far', 'Kib is reading your files: {done} so far', { done: formatNumber(done) });
    return { key: 'reading', icon: '↻', title, second: t('kibs.reading_2', 'You can keep asking.'), act: 'pause', label: t('kibs.pause', 'Pause') };
  }
  if (state === 'paused') {
    return { key: 'paused', icon: '⏸', title: t('kibs.paused', 'Reading is paused'), second: t('kibs.paused_2', 'Kib still answers from what it knows.'), act: 'resume', label: t('kibs.continue', 'Continue') };
  }
  if (folders === 0) {
    return { key: 'look', icon: '!', title: t('kibs.look', 'Kib needs a look'), second: t('kibs.no_folder', 'No folder is chosen, so Kib reads nothing.'), act: 'folders', label: t('kibs.choose', 'Choose folders') };
  }
  if (learn.kib_status === 'Paused' && learn.resume_time) {
    const zone = learn.schedule_time_zone ? ` ${t('kibs.zone', '({zone})', { zone: learn.schedule_time_zone })}` : '';
    return { key: 'hours', icon: '⏸', title: t('kibs.hours', 'Kib reads again at {time}', { time: learn.resume_time }) + zone, second: t('kibs.hours_2', 'You chose when Kib reads. It still answers from what it knows.'), ...none };
  }
  const waiting = Number(guard.deferred_queue_count || 0);
  if (waiting > 0) {
    return { key: 'asleep', icon: '💤', title: t('kibs.asleep', 'Kib is waiting for a drive to wake: {n, plural, one {# folder} other {# folders}}', { n: waiting }), second: t('kibs.asleep_2', 'Kib does not wake drives to read your files.'), ...none };
  }
  const failed = Number(learn.failed_count || 0);
  if (failed > 0) {
    return { key: 'look', icon: '!', title: t('kibs.look', 'Kib needs a look'), second: t('kibs.failed', '{n, plural, one {# file} other {# files}} could not be read.', { n: failed }), act: 'why', label: t('kibs.why', 'See why') };
  }
  return {
    key: 'ready',
    icon: '✓',
    title: t('kibs.ready', 'Kib is ready'),
    second: t('kibs.ready_2', 'Kib can read {folders, plural, one {# folder} other {# folders}}. It knows {files, plural, one {# file} other {# files}}.', { folders, files }),
    ...none,
  };
}

/** The line as markup: words and an icon, never a colour alone; the button only when one fits. */
export function kibStatusHtml(res) {
  const s = kibState(res);
  const cancel = s.key === 'reading' || s.key === 'paused'
    ? `<button type="button" class="btn-pill-toggle is-small" data-kibs-act="stop">${escapeHtml(t('kibs.cancel', 'Cancel reading'))}</button>`
    : '';
  const btn = (s.act ? `<button type="button" class="btn-pill-toggle is-small" data-kibs-act="${escapeHtml(s.act)}">${escapeHtml(s.label)}</button>` : '') + cancel;
  return `<div class="kib-status-line is-${escapeHtml(s.key)}" role="status">
    <span class="kib-status-icon" aria-hidden="true">${escapeHtml(s.icon)}</span>
    <div class="kib-status-text"><strong>${escapeHtml(s.title)}</strong><span>${escapeHtml(s.second)}</span></div>
    ${btn}
  </div>`;
}

/**
 * Draws the line into its mount and wires its button to the page's own actions.
 * @param {HTMLElement | null} mount
 * @param {any} res
 * @param {Record<string, () => unknown>} actions pause, resume, why, on, folders
 */
export function renderKibStatusLine(mount, res, actions = {}) {
  if (!mount) return;
  mount.innerHTML = kibStatusHtml(res);
  mount.querySelectorAll('[data-kibs-act]').forEach((el) => {
    const btn = /** @type {HTMLButtonElement} */ (el);
    const act = btn.dataset.kibsAct || '';
    if (typeof actions[act] === 'function') btn.addEventListener('click', () => actions[act]());
  });
}
