/**
 * Quieter at night (hardware report extra; owner 18 Nov), on the Hardware page: off by default.
 * The drive fans' curve reads the drives a few degrees cooler between two times; warm drives and
 * the full-speed limits are untouched (backend/services/quiet_night.py).
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';

/** The status line under the title. */
export function quietStatus(st) {
  if (!st || !st.enabled) return t('qn.st_off', 'Off');
  const base = t('qn.st_on', 'On from {start} to {end}.', { start: st.start, end: st.end });
  return st.active_now ? `${base} ${t('qn.now', 'Quieter now.')}` : base;
}

function html(st) {
  // the parts of the other hardware cards: a title with its switch, a line of help, the times in one row
  return `
    <div class="drawer-card qn-card">
      <div class="card-headline">
        <span class="card-head-title" id="qn-title">${escapeHtml(t('qn.title', 'Quieter at night'))}</span>
        <label class="switch"><input type="checkbox" id="qn-toggle" aria-labelledby="qn-title"${st.enabled ? ' checked' : ''}><span class="toggle-slider"></span></label>
      </div>
      <div class="card-instruction fw-why">${escapeHtml(t('qn.help', 'In Automatic, the drive fans turn a little slower at night: they act as if the drives were {shift} °C cooler. From {warm} °C they follow the normal curve, and at the safety limits they still run at full speed.', { shift: st.shift_c, warm: st.warm_c }))}</div>
      <div class="schedule-controls-row drw-row-xs-2">
        <span class="drw-xs-bold-muted-2" data-i18n="qn.start">${escapeHtml(t('qn.start', 'From'))}</span>
        <input type="time" id="qn-start" class="tz-text-input drw-size" aria-label="${escapeHtml(t('qn.start', 'From'))}" data-i18n-aria-label="qn.start" value="${escapeHtml(st.start)}">
        <span class="drw-xs-muted-2" data-i18n="settings.to">${escapeHtml(t('settings.to', 'to'))}</span>
        <input type="time" id="qn-end" class="tz-text-input drw-size" aria-label="${escapeHtml(t('qn.end', 'Until'))}" data-i18n-aria-label="qn.end" value="${escapeHtml(st.end)}">
      </div>
      <p class="card-instruction qn-status" id="qn-status" aria-live="polite">${escapeHtml(quietStatus(st))}</p>
      <div class="fw-error" id="qn-error" role="alert" hidden></div>
    </div>`;
}

export async function renderQuietNightCard(mount = document.getElementById('quiet-night-card')) {
  if (!mount) return null;
  let st;
  try {
    st = await api.get('/api/fans/quiet-night');
  } catch {
    mount.hidden = true;
    return null;
  }
  mount.innerHTML = html(st);
  mount.hidden = false;
  const err = /** @type {HTMLElement} */ (mount.querySelector('#qn-error'));
  const send = async (enabled) => {
    err.hidden = true;
    try {
      await api.put('/api/fans/quiet-night', {
        enabled,
        start: /** @type {HTMLInputElement} */ (mount.querySelector('#qn-start')).value,
        end: /** @type {HTMLInputElement} */ (mount.querySelector('#qn-end')).value,
      });
      await renderQuietNightCard(mount);
    } catch (e) {
      err.textContent = e instanceof Error ? e.message : String(e);
      err.hidden = false;
    }
  };
  // like the light's night schedule: the switch and the times take effect as they change
  const toggle = /** @type {HTMLInputElement} */ (mount.querySelector('#qn-toggle'));
  toggle.addEventListener('change', () => send(toggle.checked));
  for (const id of ['#qn-start', '#qn-end']) {
    /** @type {HTMLElement} */ (mount.querySelector(id)).addEventListener('change', () => send(st.enabled));
  }
  return st;
}
