/**
 * SNMP v3 on Connections → Monitoring tools (owner decision, 16 Nov 2026): off by default, version 3
 * only. The two passwords are sent once and never come back; the card only says they are saved.
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';

/** The status line: off, answering on a port, or why it does not answer. */
export function snmpStatus(st) {
  if (!st || !st.enabled) return t('snmp.st_off', 'Off');
  if (st.error) return t('snmp.st_error', 'Not answering: {error}', { error: st.error });
  if (st.running)
    return t('snmp.st_on', 'Answers SNMP v3 on UDP {port} as {user}.', {
      port: st.listening_port || st.port,
      user: st.user,
    });
  return t('snmp.st_starting', 'On, starting…');
}

function html(st) {
  const p = st.protocols || { auth: 'SHA-256', priv: 'AES-128' };
  const saved = st.passwords_set ? t('snmp.pw_saved', 'Saved; type a new one to change it') : '';
  return `
    <div class="nsv-row-3">
      <div class="nsv-row-4">
        <span class="nsv-fs18" aria-hidden="true">📈</span>
        <div>
          <div class="nsv-fs13-bold-strong" id="snmp-title">${escapeHtml(t('snmp.title', 'SNMP for monitoring tools'))}</div>
          <div class="nsv-xs-muted" id="snmp-status" aria-live="polite">${escapeHtml(snmpStatus(st))}</div>
        </div>
      </div>
      <button type="button" class="btn-pill-toggle" id="snmp-toggle" aria-pressed="${st.enabled ? 'true' : 'false'}" aria-labelledby="snmp-title">${escapeHtml(st.enabled ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off'))}</button>
    </div>
    <div class="nsv-xs-muted-2">${escapeHtml(t('snmp.help', 'Lets tools such as LibreNMS, Zabbix or PRTG read uptime, memory, storage, processor load and network traffic. Version 3 only: a tool needs the user name and both passwords, and nothing can be changed over SNMP. Kiboto must be reachable on UDP {port} (map it in the container settings if Kiboto runs in its own network).', { port: st.port }))}</div>
    <form class="ddns-form" id="snmp-form">
      <label class="ddns-field"><span>${escapeHtml(t('snmp.user', 'User name'))}</span>
        <input id="snmp-user" type="text" autocomplete="off" spellcheck="false" maxlength="32" value="${escapeHtml(st.user || '')}" placeholder="monitor"></label>
      <label class="ddns-field"><span>${escapeHtml(t('snmp.auth', 'Authentication password ({protocol})', { protocol: p.auth }))}</span>
        <input id="snmp-auth" type="password" autocomplete="new-password" minlength="8" placeholder="${escapeHtml(saved)}"></label>
      <label class="ddns-field"><span>${escapeHtml(t('snmp.priv', 'Encryption password ({protocol})', { protocol: p.priv }))}</span>
        <input id="snmp-priv" type="password" autocomplete="new-password" minlength="8" placeholder="${escapeHtml(saved)}"></label>
      <label class="ddns-field"><span>${escapeHtml(t('snmp.port', 'Port (UDP)'))}</span>
        <input id="snmp-port" type="number" min="1" max="65535" value="${escapeHtml(String(st.port || 161))}"></label>
      <label class="ddns-field"><span>${escapeHtml(t('snmp.location', 'Where the NAS stands (optional)'))}</span>
        <input id="snmp-location" type="text" maxlength="255" value="${escapeHtml(st.location || '')}"></label>
      <label class="ddns-field"><span>${escapeHtml(t('snmp.contact', 'Who to contact (optional)'))}</span>
        <input id="snmp-contact" type="text" maxlength="255" value="${escapeHtml(st.contact || '')}"></label>
      <div class="ddns-actions">
        <button type="submit" class="btn-pill-toggle is-primary" id="snmp-save">${escapeHtml(t('ddns.save', 'Save'))}</button>
      </div>
      <div class="ddns-error" id="snmp-error" role="alert" hidden></div>
    </form>`;
}

/** Draws the card into mount and wires it; returns the state shown. */
export async function renderSnmpCard(mount = document.getElementById('conn-snmp-card')) {
  if (!mount) return null;
  let st;
  try {
    st = await api.get('/api/network/snmp');
  } catch (e) {
    mount.innerHTML = `<div class="nsv-xs-muted">${escapeHtml(t('snmp.load_failed', 'SNMP could not be loaded: {error}', { error: e instanceof Error ? e.message : String(e) }))}</div>`;
    return null;
  }
  mount.innerHTML = html(st);
  const $ = (id) => /** @type {any} */ (mount.querySelector(`#${id}`));
  const err = $('snmp-error');
  const say = (msg) => {
    err.textContent = msg;
    err.hidden = !msg;
  };
  const send = async (enabled) => {
    say('');
    const auth = $('snmp-auth').value;
    const priv = $('snmp-priv').value;
    try {
      await api.put('/api/network/snmp', {
        enabled,
        port: Number($('snmp-port').value) || 161,
        user: $('snmp-user').value.trim(),
        auth_password: auth ? auth : null,
        priv_password: priv ? priv : null,
        location: $('snmp-location').value,
        contact: $('snmp-contact').value,
      });
      await renderSnmpCard(mount);
    } catch (e) {
      if (/** @type {any} */ (e)?.error === 'cancelled') return;
      say(e instanceof Error ? e.message : String(e));
    }
  };
  $('snmp-form').addEventListener('submit', (e) => {
    e.preventDefault();
    send(Boolean(st.enabled));
  });
  $('snmp-toggle').addEventListener('click', () => send(!st.enabled));
  return st;
}
