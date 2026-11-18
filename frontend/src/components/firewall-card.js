/**
 * Firewall on the Security page (audit A13): off by default; which services stay reachable, from
 * the home network or from anywhere. Where Kiboto can't manage the NAS's firewall (in a container
 * on Unraid or TrueNAS) it says why and the switch stays off.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';

const NAMES = () => ({
  web: t('fw.s_web', 'Kiboto (this page)'),
  ssh: t('fw.s_ssh', 'SSH sign-in'),
  smb: t('fw.s_smb', 'Shared folders (Windows and Mac)'),
  nfs: t('fw.s_nfs', 'Shared folders (NFS, Linux)'),
  webdav: 'WebDAV',
  sftp: 'SFTP',
  tailscale: 'Tailscale',
  mdns: t('fw.s_mdns', 'Finding this NAS by name on the network'),
});

/** Why the switch is off here, in words, or "" where Kiboto can manage the firewall. */
export function whyNot(code) {
  if (code === 'host')
    return t(
      'fw.why_host',
      "Kiboto runs in a container on this NAS, so the NAS's own firewall applies (on Unraid or TrueNAS, set it there). Kiboto manages the firewall on its own system images."
    );
  if (code === 'no_nft') return t('fw.why_nft', 'The nft tool is missing, so Kiboto cannot load firewall rules here.');
  if (code === 'no_cap')
    return t('fw.why_cap', 'Kiboto lacks the network permission (NET_ADMIN) it needs to load firewall rules.');
  return '';
}

function html(st) {
  const names = NAMES();
  const lock = !st.possible;
  const rows = Object.keys(names)
    .map(
      (id) => `
      <label class="fw-row"><input type="checkbox" data-fw-svc="${id}"${st.services[id] ? ' checked' : ''}${id === 'web' ? ' disabled' : ''}>
        <span>${escapeHtml(names[id])}${id === 'web' ? ` <span class="fw-note">${escapeHtml(t('fw.web_always', "always reachable from home, so you can't lock yourself out"))}</span>` : ''}</span></label>`
    )
    .join('');
  return `
    <div class="fw-head">
      <div>
        <h3 class="account-h" id="fw-title">${escapeHtml(t('fw.title', 'Firewall'))}</h3>
        <p class="fw-status" id="fw-status">${escapeHtml(st.enabled ? t('fw.on', 'On: only the services below can be reached.') : t('fw.off', 'Off: every service on this NAS can be reached.'))}</p>
      </div>
      <button type="button" class="btn-pill-toggle" id="fw-toggle" aria-pressed="${st.enabled ? 'true' : 'false'}" aria-labelledby="fw-title"${lock ? ' disabled' : ''}>${escapeHtml(st.enabled ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off'))}</button>
    </div>
    ${lock ? `<p class="fw-why" id="fw-why">${escapeHtml(whyNot(st.why_not))}</p>` : ''}
    <fieldset class="fw-set"${lock ? ' disabled' : ''}>
      <legend>${escapeHtml(t('fw.who', 'Who can connect'))}</legend>
      <label class="fw-row"><input type="radio" name="fw-from" value="lan"${st.allow_from !== 'anywhere' ? ' checked' : ''}> ${escapeHtml(t('fw.lan', 'Only devices at home (and Tailscale)'))}</label>
      <label class="fw-row"><input type="radio" name="fw-from" value="anywhere"${st.allow_from === 'anywhere' ? ' checked' : ''}> ${escapeHtml(t('fw.anywhere', 'Any address'))}</label>
    </fieldset>
    <fieldset class="fw-set"${lock ? ' disabled' : ''}>
      <legend>${escapeHtml(t('fw.services', 'Services that stay reachable'))}</legend>${rows}
    </fieldset>
    <details class="fw-rules" data-advanced-only><summary>${escapeHtml(t('fw.show_rules', 'Show the rules'))}</summary><pre translate="no">${escapeHtml(st.rules || '')}</pre></details>
    <div class="fw-error" id="fw-error" role="alert" hidden></div>`;
}

/** Draws the card into mount; returns the state shown. */
export async function renderFirewallCard(mount = document.getElementById('firewall-card')) {
  if (!mount) return null;
  let st;
  try {
    st = await api.get('/api/security/firewall');
  } catch {
    mount.hidden = true; // not an administrator, or the server is older
    return null;
  }
  mount.innerHTML = html(st);
  mount.hidden = false;
  const err = /** @type {HTMLElement} */ (mount.querySelector('#fw-error'));
  const send = async (enabled) => {
    err.hidden = true;
    const services = {};
    mount.querySelectorAll('[data-fw-svc]').forEach((b) => {
      services[/** @type {HTMLInputElement} */ (b).dataset.fwSvc] = /** @type {HTMLInputElement} */ (b).checked;
    });
    const from = /** @type {HTMLInputElement | null} */ (mount.querySelector('input[name="fw-from"]:checked'));
    try {
      await api.put('/api/security/firewall', { enabled, allow_from: from ? from.value : 'lan', services });
      await renderFirewallCard(mount);
    } catch (e) {
      err.textContent = e instanceof Error ? e.message : String(e);
      err.hidden = false;
    }
  };
  mount.querySelector('#fw-toggle')?.addEventListener('click', () => send(!st.enabled));
  mount.querySelectorAll('.fw-set input').forEach((i) => i.addEventListener('change', () => send(st.enabled)));
  return st;
}
