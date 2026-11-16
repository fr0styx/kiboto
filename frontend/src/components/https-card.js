/**
 * HTTPS at home (audit A9) on Away from home: a Let's Encrypt certificate for the Dynamic DNS name,
 * proved with a DNS record (no open port needed), renewed by itself. Off by default.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';

/** The status line. */
export function httpsStatus(st) {
  if (!st || !st.enabled) return t('https.st_off', 'Off');
  if (st.last_error) return t('https.st_error', 'No certificate: {error}', { error: st.last_error });
  if (st.has_cert) {
    return st.serving
      ? t('https.st_on', 'https://{name}:{port} works; the certificate renews by itself ({days} days left).', { name: st.hostname, port: st.port, days: st.days_left })
      : t('https.st_cert', 'Certificate ready for {name} ({days} days left).', { name: st.hostname, days: st.days_left });
  }
  return t('https.st_none', 'On: press "Get a certificate".');
}

function html(st) {
  return `
    <div class="nsv-row-3">
      <div class="nsv-row-4">
        <span class="nsv-fs18" aria-hidden="true">🔒</span>
        <div>
          <div class="nsv-fs13-bold-strong" id="https-title">${escapeHtml(t('https.title', 'HTTPS at home'))}</div>
          <div class="nsv-xs-muted" id="https-status" aria-live="polite">${escapeHtml(httpsStatus(st))}</div>
        </div>
      </div>
      <button type="button" class="btn-pill-toggle" id="https-toggle" aria-pressed="${st.enabled ? 'true' : 'false'}" aria-labelledby="https-title"${st.ddns_ready ? '' : ' disabled'}>${escapeHtml(st.enabled ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off'))}</button>
    </div>
    <div class="nsv-xs-muted-2">${escapeHtml(st.ddns_ready
      ? t('https.help', 'A Let\'s Encrypt certificate for {name}, proved through your Dynamic DNS service, so browsers trust https://{name}:{port}. Kiboto must be reachable on port {port} (map it in the container settings), and at home the name must lead to this NAS (your router or local DNS).', { name: st.ddns_hostname, port: st.port })
      : t('https.need_ddns', 'Set up Dynamic DNS above first: the certificate is for that name.'))}</div>
    ${st.enabled ? `<div class="ddns-actions">
      <button type="button" class="btn-pill-toggle is-primary" id="https-get">${escapeHtml(st.has_cert ? t('https.renew', 'Renew now') : t('https.get', 'Get a certificate'))}</button>
    </div>
    <div class="nsv-xs-muted-2">${escapeHtml(t('https.terms', 'Getting a certificate accepts the Let\'s Encrypt Subscriber Agreement:'))} <a href="${escapeHtml(st.terms)}" target="_blank" rel="noopener">letsencrypt.org/repository</a></div>` : ''}
    <div class="ddns-error" id="https-error" role="alert" hidden></div>`;
}

export async function renderHttpsCard(mount = document.getElementById('https-card')) {
  if (!mount) return null;
  let st;
  try {
    st = await api.get('/api/network/https');
  } catch {
    mount.hidden = true;
    return null;
  }
  mount.innerHTML = html(st);
  mount.hidden = false;
  const err = /** @type {HTMLElement} */ (mount.querySelector('#https-error'));
  const fail = (e) => { err.textContent = e instanceof Error ? e.message : String(e); err.hidden = false; };
  mount.querySelector('#https-toggle')?.addEventListener('click', async () => {
    try {
      await api.put('/api/network/https', { enabled: !st.enabled, staging: !!st.staging });
      await renderHttpsCard(mount);
    } catch (e) { fail(e); }
  });
  mount.querySelector('#https-get')?.addEventListener('click', async (e) => {
    const btn = /** @type {HTMLButtonElement} */ (e.currentTarget);
    btn.disabled = true;
    btn.textContent = t('https.working', 'Asking Let\'s Encrypt (about a minute)…');
    try {
      await api.post('/api/network/https/certificate', {});
      await renderHttpsCard(mount);
    } catch (e2) { fail(e2); btn.disabled = false; }
  });
  return st;
}
