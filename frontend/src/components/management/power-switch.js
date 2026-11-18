/**
 * "Restart or shut down" on Power (SET-31, Power stage 4; X5: Power, and later the top bar). Two
 * buttons, each confirmed by the server (428 until the person agrees); greyed with the reason where
 * nothing can restart or switch off this host, so nothing is stopped for a command that cannot run.
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';
import { showToast } from '../../toast.js';
import { currentUser, hasScope } from '../../route-access.js';

/** Why Restart or Shut down cannot work here, in the reader's language when the server sent a key. */
export function whyNot(c) {
  const key = c && c.text && c.text.msg_key;
  return key ? t(key, c.why || '', c.text.params || {}) : (c && c.why) || '';
}

/** What a button says it did, or why not. */
export function switchSaid(action, ok, error = '') {
  if (ok)
    return action === 'reboot'
      ? t('pws.rebooting', 'The NAS is restarting. This page comes back when it is up again.')
      : t('pws.shutting', 'The NAS is shutting down. Switch it on again with its power button.');
  return t('pws.failed', 'Nothing was switched: {error}', { error });
}

/**
 * Draws the section once per opening of Power.
 * @param {HTMLElement | null} mount
 */
export async function renderPowerSwitch(mount) {
  if (!mount || mount.dataset.drawn === '1') return;
  const user = currentUser();
  if (user && !hasScope(user.scopes || [], 'system:power')) {
    mount.hidden = true; // not this person's to do: no buttons that only answer "no permission"
    return;
  }
  let can;
  try {
    can = await api.get('/api/system/power-actions');
  } catch (_) {
    mount.hidden = true; // not this person's to do
    return;
  }
  mount.dataset.drawn = '1';
  const rowHtml = (action, label) => {
    const c = can?.[action] || { ok: false, why: '' };
    const key = escapeHtml(action);
    return `<div class="pwc-item">
      <button type="button" class="btn-pill-toggle${action === 'shutdown' ? ' is-danger' : ''}" data-power-action="${key}"${c.ok ? '' : ` disabled aria-describedby="pws-why-${key}"`}>${escapeHtml(label)}</button>
      ${c.ok ? '' : `<p class="pwc-line" id="pws-why-${key}">${escapeHtml(whyNot(c))}</p>`}
    </div>`;
  };
  mount.innerHTML = `
    <h3 class="pwc-title">${escapeHtml(t('pws.title', 'Restart or shut down'))}</h3>
    <p class="pwc-line">${escapeHtml(t('pws.desc', 'Running virtual machines are asked to shut down first. Everyone using the NAS loses their connection until it is back.'))}</p>
    ${rowHtml('reboot', t('pws.reboot', 'Restart the NAS'))}
    ${rowHtml('shutdown', t('pws.shutdown', 'Shut down the NAS'))}`;
  mount.hidden = false;
  mount.querySelectorAll('[data-power-action]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const action = /** @type {HTMLElement} */ (btn).dataset.powerAction || '';
      /** @type {HTMLButtonElement} */ (btn).disabled = true;
      try {
        await api.post(`/api/system/${action}`, {});
        showToast(switchSaid(action, true), 'info');
      } catch (e) {
        /** @type {HTMLButtonElement} */ (btn).disabled = false;
        if (/** @type {any} */ (e)?.error === 'cancelled') return;
        showToast(switchSaid(action, false, e instanceof Error ? e.message : String(e)), 'error');
      }
    });
  });
}
