/**
 * Settings copy on your pools (Backup), on a machine set up for Kiboto: per pool, when the
 * encrypted copy of Kiboto's settings on it was last written, and a button to write it now. A
 * sleeping pool is never woken for it. Where Kiboto is a guest the card stays hidden.
 */
import { api } from '../api.js';
import { formatDateTime } from '../format.js';
import { html } from '../html.js';
import { t } from '../i18n.js';

/** What a pool's line says; `done` is what "Copy now" just answered for it. */
export function poolCopyLine(pool, done = '') {
  if (done === 'asleep') return t('pcopy.asleep', 'Asleep: it keeps the copy it has');
  if (pool.error) return t('pcopy.failed', 'Last try failed: {error}', { error: pool.error });
  if (!pool.at) return t('pcopy.never', 'No copy yet');
  return t('pcopy.at', 'Copied {when}', { when: formatDateTime(new Date(pool.at * 1000)) });
}

/** Draws the card into mount and wires it; returns the state shown (null when there is none). */
export async function renderPoolCopyCard(mount = document.getElementById('pool-copy-card'), shown = null) {
  if (!mount) return null;
  let st = shown;
  if (!st) {
    try {
      st = await api.get('/api/system/settings-copy');
    } catch {
      st = null; // an older server, or no right to see it: no card
    }
  }
  if (!st || !st.managed) {
    mount.hidden = true;
    mount.innerHTML = '';
    return st;
  }
  const pools = st.pools || [];
  const done = st.done || {};
  const locked = t(
    'pcopy.locked',
    "No copy can be written until the recovery key has opened this machine's data key (Security)."
  );
  const none = t('pcopy.none', 'No pools yet. The copy starts with your first pool.');
  const whyNot = st.locked ? locked : pools.length ? '' : none;
  mount.innerHTML = html`<h2 class="account-h" id="pcopy-title">${t('pcopy.title', 'Settings copy on your pools')}</h2>
    <p class="fw-why">
      ${t(
        'pcopy.help',
        'Kiboto keeps an encrypted copy of its settings on every pool. If the system disk fails, a fresh Kiboto and your recovery key bring your people, shared folders and apps back. A sleeping pool is not woken for it.'
      )}
    </p>
    ${st.locked ? html`<p class="fw-why" id="pcopy-locked">${locked}</p>` : ''}
    ${
      pools.length
        ? html`<ul class="pcopy-list" aria-labelledby="pcopy-title">
          ${pools.map(
            (p) =>
              html`<li><strong translate="no">${p.name}</strong> <span>${poolCopyLine(p, done[p.name])}</span></li>`
          )}
        </ul>`
        : html`<p class="fw-why" id="pcopy-none">${none}</p>`
    }
    <div class="ddns-actions">
      <button type="button" class="btn-pill-toggle" id="pcopy-now" title="${whyNot}" ${whyNot ? 'disabled' : ''}>
        ${t('pcopy.now', 'Copy now')}
      </button>
    </div>
    <div class="fw-error" id="pcopy-error" role="alert" hidden></div>`;
  mount.hidden = false;
  const button = /** @type {HTMLButtonElement} */ (mount.querySelector('#pcopy-now'));
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      await renderPoolCopyCard(mount, await api.post('/api/system/settings-copy/now', {}));
    } catch (e) {
      const err = /** @type {HTMLElement} */ (mount.querySelector('#pcopy-error'));
      err.textContent = e instanceof Error ? e.message : String(e);
      err.hidden = false;
      button.disabled = false;
    }
  });
  return st;
}
