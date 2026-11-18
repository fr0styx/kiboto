/**
 * Switch off when too hot (hardware report extra; owner 18 Nov), on the Power page: off by default.
 * A last line of defence when the fans can't keep up; the fans themselves are not touched.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';
import { formatDateTime } from '../format.js';

/** The status line under the title. */
export function heatStatus(st) {
  if (!st || !st.enabled) return t('heat.st_off', 'Off');
  const what = st.can_power_off
    ? t(
        'heat.st_on',
        'On: a hard drive at {hdd} °C or an NVMe drive at {nvme} °C for {min} minutes switches the NAS off.',
        { hdd: st.hdd_c, nvme: st.nvme_c, min: st.hold_min }
      )
    : t(
        'heat.st_on_apps',
        'On: a hard drive at {hdd} °C or an NVMe drive at {nvme} °C for {min} minutes stops the apps and virtual machines.',
        { hdd: st.hdd_c, nvme: st.nvme_c, min: st.hold_min }
      );
  const last = st.last;
  if (!last || !last.at) return what;
  const when = formatDateTime(last.at * 1000);
  if (last.outcome === 'off')
    return `${what} ${t('heat.last_off', 'Last time ({when}) it switched the NAS off.', { when })}`;
  return `${what} ${t('heat.last_hand', 'Last time ({when}) it stopped the apps; the NAS had to be switched off by hand.', { when })}`;
}

function html(st) {
  return `
    <div class="fw-head">
      <div>
        <h3 class="account-h" id="heat-title">${escapeHtml(t('heat.title', 'Switch off when too hot'))}</h3>
        <p class="fw-status" id="heat-status" aria-live="polite">${escapeHtml(heatStatus(st))}</p>
      </div>
      <button type="button" class="btn-pill-toggle" id="heat-toggle" aria-pressed="${st.enabled ? 'true' : 'false'}" aria-labelledby="heat-title heat-toggle">${escapeHtml(st.enabled ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off'))}</button>
    </div>
    <p class="fw-why">${escapeHtml(
      st.can_power_off
        ? t(
            'heat.help',
            'A last line of defence when the fans cannot keep up, say a fan has failed or a vent is blocked. Kiboto warns you first, then stops the virtual machines and apps, saves what is in memory and switches the NAS off. Sleeping drives are never woken for it.'
          )
        : t(
            'heat.help_apps',
            "A last line of defence when the fans cannot keep up. Kiboto can't switch this NAS off by itself, so it warns you, stops the virtual machines and apps to cool it down, and asks you to switch it off by hand. Sleeping drives are never woken for it."
          )
    )}</p>
    <div class="fw-error" id="heat-error" role="alert" hidden></div>`;
}

export async function renderHeatShutdownCard(mount = document.getElementById('heat-shutdown-card')) {
  if (!mount) return null;
  let st;
  try {
    st = await api.get('/api/system/heat-shutdown');
  } catch {
    mount.hidden = true;
    return null;
  }
  mount.innerHTML = html(st);
  mount.hidden = false;
  const err = /** @type {HTMLElement} */ (mount.querySelector('#heat-error'));
  mount.querySelector('#heat-toggle')?.addEventListener('click', async () => {
    err.hidden = true;
    try {
      await api.put('/api/system/heat-shutdown', { enabled: !st.enabled });
      await renderHeatShutdownCard(mount);
    } catch (e) {
      err.textContent = e instanceof Error ? e.message : String(e);
      err.hidden = false;
    }
  });
  return st;
}
