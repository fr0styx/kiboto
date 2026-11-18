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
  return `
    <div class="fw-head">
      <div>
        <h3 class="account-h" id="qn-title">${escapeHtml(t('qn.title', 'Quieter at night'))}</h3>
        <p class="fw-status" id="qn-status" aria-live="polite">${escapeHtml(quietStatus(st))}</p>
      </div>
      <button type="button" class="btn-pill-toggle" id="qn-toggle" aria-pressed="${st.enabled ? 'true' : 'false'}" aria-labelledby="qn-title">${escapeHtml(st.enabled ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off'))}</button>
    </div>
    <p class="fw-why">${escapeHtml(t('qn.help', 'In Automatic, the drive fans turn a little slower at night: they act as if the drives were {shift} °C cooler. From {warm} °C they follow the normal curve, and at the safety limits they still run at full speed.', { shift: st.shift_c, warm: st.warm_c }))}</p>
    <div class="ps-times">
      <label class="ddns-field"><span>${escapeHtml(t('qn.start', 'From'))}</span><input type="time" id="qn-start" value="${escapeHtml(st.start)}"></label>
      <label class="ddns-field"><span>${escapeHtml(t('qn.end', 'Until'))}</span><input type="time" id="qn-end" value="${escapeHtml(st.end)}"></label>
    </div>
    <div class="ddns-actions"><button type="button" class="btn-pill-toggle is-primary" id="qn-save">${escapeHtml(t('ddns.save', 'Save'))}</button></div>
    <div class="fw-error" id="qn-error" role="alert" hidden></div>`;
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
  mount.querySelector('#qn-toggle')?.addEventListener('click', () => send(!st.enabled));
  mount.querySelector('#qn-save')?.addEventListener('click', () => send(st.enabled));
  return st;
}
