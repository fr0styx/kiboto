/**
 * Power history in sentences (SET-31, Power stage 3; Power report section 4, item 5). The ledger
 * was a five-column table of codes ("OUTAGE_RECOVERED", "Battery Delta 98% ➔ 71%"). Now: when, and
 * what happened, as one sentence; the last five first, "Show all" opens the rest in place.
 */
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';
import { formatDateTime } from '../../format.js';

export const FIRST_ROWS = 5;

/** A duration in words: seconds, minutes or hours. */
export function lasted(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  if (s < 90) return t('pwh.secs', '{count, plural, one {# second} other {# seconds}}', { count: s });
  if (s < 5400) return t('pwh.mins', '{count, plural, one {# minute} other {# minutes}}', { count: Math.round(s / 60) });
  return t('pwh.hours', '{count, plural, one {# hour} other {# hours}}', { count: Math.round(s / 3600) });
}

/** One event as a sentence. */
export function historySentence(ev) {
  const start = ev?.start_battery_pct;
  const end = ev?.end_battery_pct;
  switch (ev?.event_type) {
    case 'OUTAGE_RECOVERED':
      return start != null && end != null
        ? t('pwh.cut_battery', 'The power was out for {time}. The battery went from {start} % to {end} %.', { time: lasted(ev.duration_sec), start: Math.round(start), end: Math.round(end) })
        : t('pwh.cut', 'The power was out for {time}.', { time: lasted(ev.duration_sec) });
    case 'FAILSAFE_SHUTDOWN':
      return end != null
        ? t('pwh.shutdown_battery', 'The battery ran low ({end} % left), and the NAS was shut down safely.', { end: Math.round(end) })
        : t('pwh.shutdown', 'The battery ran low, and the NAS was shut down safely.');
    case 'SELF_TEST':
      return t('pwh.self_test', 'A battery test was sent to the UPS.');
    case 'OUTAGE_SIMULATION':
      return t('pwh.practice', 'Practice run: Kiboto acted as if the power were out. Nothing was shut down.');
    default:
      return String(ev?.action_taken || ev?.event_type || '');
  }
}

/**
 * Draws the list; with more than FIRST_ROWS events, "Show all" opens the rest in place.
 * @param {HTMLElement | null} mount
 * @param {any[]} events newest first
 */
export function renderPowerHistory(mount, events) {
  if (!mount) return;
  const list = Array.isArray(events) ? events : [];
  if (!list.length) {
    mount.innerHTML = `<p class="pwh-empty">${escapeHtml(t('pwh.none', 'No power cuts recorded yet.'))}</p>`;
    return;
  }
  const all = mount.dataset.all === '1';
  const shown = all ? list : list.slice(0, FIRST_ROWS);
  mount.innerHTML = `<ol class="pwh-list">${shown.map((ev) => `<li class="pwh-row"><span class="pwh-when">${escapeHtml(formatDateTime(Number(ev.ts) * (Number(ev.ts) < 1e12 ? 1000 : 1)))}</span> <span class="pwh-what">${escapeHtml(historySentence(ev))}</span></li>`).join('')}</ol>${
    list.length > FIRST_ROWS && !all ? `<button type="button" class="btn-pill-toggle pwh-more">${escapeHtml(t('pwh.show_all', 'Show all ({count})', { count: list.length }))}</button>` : ''}`;
  mount.querySelector('.pwh-more')?.addEventListener('click', () => {
    mount.dataset.all = '1';
    renderPowerHistory(mount, list);
  });
}
