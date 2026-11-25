/**
 * Firewall on the Security page (audit A13): off by default. When it is on, the home network
 * reaches everything on this NAS and the outside reaches only what is ticked here. Where Kiboto
 * can't manage the NAS's firewall (in a container on Unraid or TrueNAS) it says why and the
 * switch stays off.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { serverSaid } from '../server-text.js';
import { escapeHtml } from '../utils.js';

const NAMES = () => ({
  web: t('fw.s_web', 'Kiboto (this page)'),
  ssh: t('fw.s_ssh', 'SSH sign-in'),
  smb: t('fw.s_smb', 'Shared folders (Windows and Mac)'),
  nfs: t('fw.s_nfs', 'Shared folders (NFS, Linux)'),
  webdav: 'WebDAV',
  sftp: 'SFTP',
  tailscale: 'Tailscale',
  apps: t('fw.s_apps', 'Apps (the ports they publish)'),
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

/** The one line under the title: what on and off mean. */
export function firewallStatus(st) {
  return st?.enabled
    ? t(
        'fw.on_home',
        'On: devices at home reach everything on this NAS. From outside your home, only what is ticked below.'
      )
    : t('fw.off_all', 'Off: anything that can reach this NAS can reach every service on it.');
}

function html(st) {
  const names = NAMES();
  const lock = !st.possible;
  const outside = st.outside || {};
  const rows = Object.keys(names)
    .map(
      (id) => `
      <label class="fw-row"><input type="checkbox" data-fw-svc="${id}"${outside[id] ? ' checked' : ''}>
        <span>${escapeHtml(names[id])}</span></label>`
    )
    .join('');
  return `
    <div class="fw-head">
      <div>
        <h3 class="account-h" id="fw-title">${escapeHtml(t('fw.title', 'Firewall'))}</h3>
        <p class="fw-status" id="fw-status">${escapeHtml(firewallStatus(st))}</p>
      </div>
      <button type="button" class="btn-pill-toggle${st.enabled ? ' active' : ''}" id="fw-toggle" aria-pressed="${st.enabled ? 'true' : 'false'}" aria-labelledby="fw-title fw-toggle"${lock ? ' disabled' : ''}>${escapeHtml(st.enabled ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off'))}</button>
    </div>
    ${lock ? `<p class="fw-why" id="fw-why">${escapeHtml(whyNot(st.why_not))}</p>` : ''}
    <fieldset class="fw-set"${lock ? ' disabled' : ''}>
      <legend>${escapeHtml(t('fw.outside', 'Reachable from outside your home'))}</legend>${rows}
    </fieldset>
    <p class="fw-note" id="fw-home-note">${escapeHtml(t('fw.home_note', 'Your home network is: private addresses, Tailscale, and the IPv6 network this NAS is on.'))}</p>
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
    const outside = {};
    mount.querySelectorAll('[data-fw-svc]').forEach((b) => {
      outside[/** @type {HTMLInputElement} */ (b).dataset.fwSvc] = /** @type {HTMLInputElement} */ (b).checked;
    });
    try {
      await api.put('/api/security/firewall', { enabled, outside });
      await renderFirewallCard(mount);
    } catch (e) {
      // a refusal comes in the reader's language where the server said how it was made
      err.textContent = serverSaid(e?.body, e instanceof Error ? e.message : String(e));
      err.hidden = false;
    }
  };
  mount.querySelector('#fw-toggle')?.addEventListener('click', () => send(!st.enabled));
  mount.querySelectorAll('.fw-set input').forEach((i) => i.addEventListener('change', () => send(st.enabled)));
  return st;
}
