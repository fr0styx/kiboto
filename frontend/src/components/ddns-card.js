/**
 * Dynamic DNS on Away from home (audit A8, owner decision 16 Nov 2026): DuckDNS or Cloudflare, off
 * by default. The token is sent once and never comes back; the card only says it is saved.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';
import { formatTime } from '../format.js';

const SERVICES = { duckdns: 'DuckDNS', cloudflare: 'Cloudflare' }; // product names, the same in every language

/** The status line: off, on and working, on with an error, or on and not run yet. */
export function ddnsStatus(st) {
  if (!st || !st.enabled) return t('ddns.st_off', 'Off');
  if (st.last_error) return t('ddns.st_error', 'Not updated: {error}', { error: st.last_error });
  if (st.last_ok) {
    return t('ddns.st_ok', '{name} points to {ip} (checked {time})', {
      name: st.hostname,
      ip: st.last_ip || '?',
      time: formatTime(new Date(st.last_ok * 1000)),
    });
  }
  return t('ddns.st_waiting', 'On: {name} is updated within 5 minutes', { name: st.hostname });
}

function html(st) {
  const cf = st.provider === 'cloudflare';
  return `
    <div class="nsv-row-3">
      <div class="nsv-row-4">
        <span class="nsv-fs18" aria-hidden="true">🏷️</span>
        <div>
          <div class="nsv-fs13-bold-strong" id="ddns-title">${escapeHtml(t('ddns.title', 'A name for your home address (Dynamic DNS)'))}</div>
          <div class="nsv-xs-muted" id="ddns-status" aria-live="polite">${escapeHtml(ddnsStatus(st))}</div>
        </div>
      </div>
      <button type="button" class="btn-pill-toggle" id="ddns-toggle" aria-pressed="${st.enabled ? 'true' : 'false'}" aria-labelledby="ddns-title ddns-toggle">${escapeHtml(st.enabled ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off'))}</button>
    </div>
    <div class="nsv-xs-muted-2">${escapeHtml(t('ddns.help', "Keeps a name such as home.duckdns.org pointing at your home's internet address when it changes. A name alone opens nothing: reaching Kiboto from outside also needs a port forwarded on your router. For private access, Tailscale needs neither."))}</div>
    <form class="ddns-form" id="ddns-form">
      <label class="ddns-field"><span>${escapeHtml(t('ddns.provider', 'Service'))}</span>
        <select id="ddns-provider">
          <option value="duckdns"${cf ? '' : ' selected'}>${SERVICES.duckdns}</option>
          <option value="cloudflare"${cf ? ' selected' : ''}>${SERVICES.cloudflare}</option>
        </select></label>
      <label class="ddns-field"><span>${escapeHtml(t('ddns.name', 'Name'))}</span>
        <input id="ddns-hostname" type="text" autocomplete="off" spellcheck="false" value="${escapeHtml(st.hostname || '')}" placeholder="${cf ? 'nas.example.com' : 'home.duckdns.org'}"></label>
      <label class="ddns-field"><span>${escapeHtml(t('ddns.token', 'Token'))}</span>
        <input id="ddns-token" type="password" autocomplete="new-password" placeholder="${escapeHtml(st.token_set ? t('ddns.token_saved', 'Saved; type a new one to change it') : '')}"></label>
      <div class="nsv-xs-muted-2" id="ddns-token-help">${escapeHtml(cf ? t('ddns.cf_help', 'A Cloudflare API token with Zone: Read and DNS: Edit for this domain.') : t('ddns.duck_help', 'The token shown on duckdns.org after you sign in.'))}</div>
      <div class="ddns-actions">
        <button type="submit" class="btn-pill-toggle is-primary" id="ddns-save">${escapeHtml(t('ddns.save', 'Save'))}</button>
        <button type="button" class="btn-pill-toggle" id="ddns-now"${st.hostname && st.token_set ? '' : ' disabled'}>${escapeHtml(t('ddns.now', 'Update now'))}</button>
      </div>
      <div class="ddns-error" id="ddns-error" role="alert" hidden></div>
    </form>`;
}

/** Draws the card into mount and wires it; returns the state shown. */
export async function renderDdnsCard(mount = document.getElementById('ddns-card')) {
  if (!mount) return null;
  let st;
  try {
    st = await api.get('/api/network/ddns');
  } catch (e) {
    mount.innerHTML = `<div class="nsv-xs-muted">${escapeHtml(t('ddns.load_failed', 'Dynamic DNS could not be loaded: {error}', { error: e instanceof Error ? e.message : String(e) }))}</div>`;
    return null;
  }
  mount.innerHTML = html(st);
  const $ = (id) => /** @type {any} */ (mount.querySelector(`#${id}`));
  const err = $('ddns-error');
  const say = (msg) => {
    err.textContent = msg;
    err.hidden = !msg;
  };
  const send = async (enabled) => {
    say('');
    const token = $('ddns-token').value;
    try {
      await api.put('/api/network/ddns', {
        enabled,
        provider: $('ddns-provider').value,
        hostname: $('ddns-hostname').value,
        token: token ? token : null,
      });
      await renderDdnsCard(mount);
    } catch (e) {
      say(e instanceof Error ? e.message : String(e));
    }
  };
  $('ddns-provider').addEventListener('change', () => {
    const cf = $('ddns-provider').value === 'cloudflare';
    $('ddns-hostname').placeholder = cf ? 'nas.example.com' : 'home.duckdns.org';
    $('ddns-token-help').textContent = cf
      ? t('ddns.cf_help', 'A Cloudflare API token with Zone: Read and DNS: Edit for this domain.')
      : t('ddns.duck_help', 'The token shown on duckdns.org after you sign in.');
  });
  $('ddns-form').addEventListener('submit', (e) => {
    e.preventDefault();
    send(st.enabled);
  });
  $('ddns-toggle').addEventListener('click', () => send(!st.enabled));
  $('ddns-now').addEventListener('click', async () => {
    say('');
    try {
      const after = await api.post('/api/network/ddns/update', {});
      $('ddns-status').textContent = ddnsStatus({ ...after, enabled: true });
      if (after.last_error) say(after.last_error);
    } catch (e) {
      say(e instanceof Error ? e.message : String(e));
    }
  });
  return st;
}
