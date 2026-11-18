/**
 * Switch off at night (audit A10) on the Power page: off by default. The NAS sets its wake-up clock
 * before it switches off, and never switches off without one.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';

const DAY_KEYS = [
  ['ps.d_mon', 'Mon'],
  ['ps.d_tue', 'Tue'],
  ['ps.d_wed', 'Wed'],
  ['ps.d_thu', 'Thu'],
  ['ps.d_fri', 'Fri'],
  ['ps.d_sat', 'Sat'],
  ['ps.d_sun', 'Sun'],
];

/** The status line under the title. */
export function scheduleStatus(st) {
  if (!st || !st.enabled) return t('ps.st_off', 'Off');
  const base = t('ps.st_on', 'Switches off at {off} and wakes at {wake}.', { off: st.off_at, wake: st.wake_at });
  if (st.last_note === 'no_wake')
    return `${base} ${t('ps.note_no_wake', 'Last time it stayed on: the wake-up clock could not be set.')}`;
  if (st.last_note === 'failed') return `${base} ${t('ps.note_failed', 'Last time switching off did not work.')}`;
  if (String(st.last_note || '').startsWith('postponed'))
    return `${base} ${t('ps.note_postponed', 'Tonight it waits: something is still running.')}`;
  return base;
}

function html(st) {
  const days = DAY_KEYS.map(
    ([k, en], i) =>
      `<label class="ps-day"><input type="checkbox" data-ps-day="${i}"${st.days.includes(i) ? ' checked' : ''}> ${escapeHtml(t(k, en))}</label>`
  ).join('');
  return `
    <div class="fw-head">
      <div>
        <h3 class="account-h" id="ps-title">${escapeHtml(t('ps.title', 'Switch off at night'))}</h3>
        <p class="fw-status" id="ps-status" aria-live="polite">${escapeHtml(scheduleStatus(st))}</p>
      </div>
      <button type="button" class="btn-pill-toggle" id="ps-toggle" aria-pressed="${st.enabled ? 'true' : 'false'}" aria-labelledby="ps-title"${st.wake_possible ? '' : ' disabled'}>${escapeHtml(st.enabled ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off'))}</button>
    </div>
    <p class="fw-why">${escapeHtml(
      st.wake_possible
        ? t(
            'ps.help',
            'Saves power while nobody uses the NAS. It sets its wake-up clock first and never switches off without one; if a backup or a virtual machine is still running it waits up to two hours. Try it for one night first and check it came back in the morning.'
          )
        : t('ps.no_wake', "This NAS's wake-up clock can't be set from Kiboto, so it would not come back on by itself.")
    )}</p>
    <div class="ps-times">
      <label class="ddns-field"><span>${escapeHtml(t('ps.off_at', 'Switch off at'))}</span><input type="time" id="ps-off" value="${escapeHtml(st.off_at)}"></label>
      <label class="ddns-field"><span>${escapeHtml(t('ps.wake_at', 'Wake up at'))}</span><input type="time" id="ps-wake" value="${escapeHtml(st.wake_at)}"></label>
    </div>
    <fieldset class="fw-set"><legend>${escapeHtml(t('ps.nights', 'Nights'))}</legend><div class="ps-days">${days}</div></fieldset>
    <div class="ddns-actions"><button type="button" class="btn-pill-toggle is-primary" id="ps-save">${escapeHtml(t('ddns.save', 'Save'))}</button></div>
    <div class="fw-error" id="ps-error" role="alert" hidden></div>`;
}

export async function renderPowerScheduleCard(mount = document.getElementById('power-schedule-card')) {
  if (!mount) return null;
  let st;
  try {
    st = await api.get('/api/system/power-schedule');
  } catch {
    mount.hidden = true;
    return null;
  }
  mount.innerHTML = html(st);
  mount.hidden = false;
  const err = /** @type {HTMLElement} */ (mount.querySelector('#ps-error'));
  const send = async (enabled) => {
    err.hidden = true;
    const days = [...mount.querySelectorAll('[data-ps-day]')]
      .filter((b) => /** @type {HTMLInputElement} */ (b).checked)
      .map((b) => Number(/** @type {HTMLInputElement} */ (b).dataset.psDay));
    try {
      await api.put('/api/system/power-schedule', {
        enabled,
        off_at: /** @type {HTMLInputElement} */ (mount.querySelector('#ps-off')).value,
        wake_at: /** @type {HTMLInputElement} */ (mount.querySelector('#ps-wake')).value,
        days,
      });
      await renderPowerScheduleCard(mount);
    } catch (e) {
      err.textContent = e instanceof Error ? e.message : String(e);
      err.hidden = false;
    }
  };
  mount.querySelector('#ps-toggle')?.addEventListener('click', () => send(!st.enabled));
  mount.querySelector('#ps-save')?.addEventListener('click', () => send(st.enabled));
  return st;
}
