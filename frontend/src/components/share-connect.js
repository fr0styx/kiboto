// How to connect, per shared folder (SET-22, Shares 3): the address for Windows and for a Mac, each
// with Copy, and which name and password to use. People with two-step sign-in need a separate
// password for shared folders (the network can't ask for a code); it is made right here.
import { api } from '../api.js';
import { t } from '../i18n.js';
import { escapeHtml, copyText } from '../utils.js';
import { showToast } from '../toast.js';

/** The two addresses, from the NAS's address (or the page's host when it has none). */
export function addresses(share, address) {
  const host = address || window.location.hostname;
  return { windows: `\\\\${host}\\${share}`, mac: `smb://${host}/${encodeURIComponent(share)}` };
}

export function connectHtml(share, a, { twoStep = false, host = '', name = '' } = {}) {
  const row = (label, value, key) =>
    `<div class="sc-row"><span class="sc-label">${escapeHtml(label)}</span><code class="sc-value">${escapeHtml(value)}</code><button type="button" class="btn-pill-toggle is-small" data-sc-copy="${key}">${escapeHtml(t('smb.copy', 'Copy'))}</button></div>`;
  const signIn = host
    ? t('sc.host_sign_in', 'Use the name and password you use for {host}.', { host })
    : name // the login name, not the name shown on People: "Administrator" was tried and refused (#71)
      ? twoStep
        ? t(
            'sc.two_step_as',
            'You have two-step sign-in, so you need a separate password for shared folders. Sign in as {name} with that password.',
            { name }
          )
        : t('sc.sign_in_as', 'Sign in as {name} with your Kiboto password.', { name })
      : twoStep
        ? t(
            'sc.two_step',
            'You have two-step sign-in, so you need a separate password for shared folders. Sign in with your Kiboto name and that password.'
          )
        : t('sc.sign_in', 'Sign in with your Kiboto name and password.');
  return `<h2 id="sc-title" class="account-h">${escapeHtml(t('sc.title', 'Connect to "{share}"', { share }))}</h2>
    ${row(t('sc.windows', 'Windows: in File Explorer, type'), a.windows, 'windows')}
    ${row(t('sc.mac', 'Mac: in Finder, Go → Connect to Server'), a.mac, 'mac')}
    <p class="sc-note">${escapeHtml(signIn)}</p>
    ${twoStep && !host ? `<p><button type="button" class="btn-pill-toggle is-primary" data-sc-make>${escapeHtml(t('sc.make', 'Make a password for shared folders'))}</button></p><div id="sc-smb-box" hidden></div>` : ''}
    <div class="sc-actions"><button type="button" class="btn-pill-toggle" data-sc-close>${escapeHtml(t('diagnostics.close_btn', 'Close'))}</button></div>`;
}

/** The window for one folder. */
export async function openConnect(share, host = '') {
  const [where, mfa, me] = await Promise.all([
    Promise.resolve()
      .then(() => api.get('/api/storage/connect'))
      .catch(() => ({ address: '' })),
    Promise.resolve()
      .then(() => api.get('/api/auth/mfa/status'))
      .catch(() => ({})),
    Promise.resolve()
      .then(() => api.get('/api/auth/me'))
      .catch(() => ({})),
  ]);
  const name = String((me?.user || me)?.username || '');
  const a = addresses(share, where?.address || '');
  document.getElementById('share-connect')?.remove();
  const dlg = document.createElement('dialog');
  dlg.id = 'share-connect';
  dlg.className = 'who-window';
  dlg.setAttribute('aria-labelledby', 'sc-title');
  dlg.innerHTML = connectHtml(share, a, { twoStep: Boolean(mfa?.mfa_enabled), host, name });
  document.body.appendChild(dlg);
  dlg.addEventListener('cancel', () => dlg.remove());
  dlg.onclick = async (e) => {
    const b = /** @type {HTMLElement} */ (e.target).closest('button');
    if (!b) return;
    if (b.hasAttribute('data-sc-close')) {
      dlg.close?.();
      dlg.remove();
    } else if (b.dataset.scCopy) {
      try {
        await copyText(a[/** @type {'windows' | 'mac'} */ (b.dataset.scCopy)]);
        b.textContent = t('smb.copied', 'Copied');
      } catch {
        showToast(t('sc.copy_failed', 'Copying was not allowed; select the address and copy it.'), 'error');
      }
    } else if (b.hasAttribute('data-sc-make')) {
      import('./smb-password.js').then((m) => m.askForSmbPassword(dlg.querySelector('#sc-smb-box'))).catch(() => {});
    }
  };
  if (typeof dlg.showModal === 'function') dlg.showModal();
  else dlg.setAttribute('open', '');
  /** @type {HTMLElement | null} */ (dlg.querySelector('[data-sc-copy]'))?.focus();
  return dlg;
}

/** "How to connect" on each card of the grid (for everyone who sees the page). */
export function addConnectButtons(grid, host = '') {
  if (!grid) return 0;
  let n = 0;
  grid.querySelectorAll('[data-share]').forEach((card) => {
    const actions = card.querySelector('.share-card-actions');
    if (!actions || actions.querySelector('[data-sc-open]')) return;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn-pill-toggle is-small';
    b.setAttribute('data-sc-open', '');
    b.textContent = t('sc.open', 'How to connect');
    b.onclick = () => openConnect(/** @type {HTMLElement} */ (card).dataset.share || '', host);
    actions.prepend(b);
    n += 1;
  });
  return n;
}
