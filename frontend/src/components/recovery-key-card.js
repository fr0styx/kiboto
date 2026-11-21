/**
 * Recovery key (Security), on a machine set up for Kiboto. That machine keeps the key that
 * encrypts the AI chats and the search index sealed to itself. The recovery key is the way back
 * after a repair or when the machine is set up again: shown until the person says they have
 * written it down, typed here when the machine could not open its data key, and replaceable.
 * Where Kiboto is a guest the card stays hidden.
 */
import { api } from '../api.js';
import { formatDate } from '../format.js';
import { html } from '../html.js';
import { t } from '../i18n.js';

/** The line under the title. */
export function recoveryKeyStatus(st) {
  if (st.locked)
    return t(
      'rkey.st_locked',
      'This machine could not open its data key, so your AI chats and the search index are closed. Type the recovery key to open them.'
    );
  if (st.to_write_down) return t('rkey.st_todo', 'Write the recovery key down and keep it away from this machine.');
  if (!st.written_down_at) return '';
  return t('rkey.st_done', 'Written down on {date}.', { date: formatDate(new Date(st.written_down_at * 1000)) });
}

function why(st) {
  return st.sealed_to === 'chip'
    ? t(
        'rkey.help_chip',
        "The key that encrypts your AI chats and search index is sealed to this machine's security chip. After a repair, or when this machine is set up again, the recovery key opens them."
      )
    : t(
        'rkey.help_disk',
        'This machine has no security chip, so the key that encrypts your AI chats and search index is kept on its system disk. After a repair, or when this machine is set up again, the recovery key opens them.'
      );
}

function controls(st) {
  if (st.locked)
    return html`<form class="ddns-form" id="rkey-form">
      <label class="ddns-field"
        ><span>${t('rkey.input', 'Recovery key')}</span>
        <input id="rkey-input" type="text" autocomplete="off" spellcheck="false" maxlength="64" placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"
      /></label>
      <div class="ddns-actions">
        <button type="submit" class="btn-pill-toggle is-primary" id="rkey-open">${t('rkey.open', 'Open')}</button>
      </div>
    </form>`;
  if (st.to_write_down)
    return html`<p class="fw-why">${t('rkey.show_note', 'Kiboto shows the key only until you say you have written it down.')}</p>
      <code class="rkey-code" id="rkey-code" translate="no" hidden></code>
      <div class="ddns-actions">
        <button type="button" class="btn-pill-toggle" id="rkey-show">${t('rkey.show', 'Show the key')}</button>
        <button type="button" class="btn-pill-toggle is-primary" id="rkey-written" hidden>${t('rkey.written', 'I have written it down')}</button>
      </div>`;
  return html`<div class="ddns-actions">
    <button type="button" class="btn-pill-toggle" id="rkey-new">${t('rkey.new', 'Make a new key')}</button>
  </div>`;
}

/** Draws the card into mount and wires it; returns the state shown (null when there is none). */
export async function renderRecoveryKeyCard(mount = document.getElementById('recovery-key-card')) {
  if (!mount) return null;
  let st;
  try {
    st = await api.get('/api/system/machine/key');
  } catch {
    st = null; // an older server, or no right to see it: no card
  }
  if (!st || !st.managed || !st.on) {
    mount.hidden = true;
    mount.innerHTML = '';
    return st;
  }
  mount.innerHTML = html`<div class="fw-head">
      <div>
        <h3 class="account-h" id="rkey-title">${t('rkey.title', 'Recovery key')}</h3>
        <p class="fw-status" id="rkey-status" aria-live="polite">${recoveryKeyStatus(st)}</p>
      </div>
    </div>
    <p class="fw-why">${why(st)}</p>
    ${controls(st)}
    <div class="fw-error" id="rkey-error" role="alert" hidden></div>`;
  mount.hidden = false;
  const $ = (id) => /** @type {any} */ (mount.querySelector(`#${id}`));
  const attempt = async (what) => {
    $('rkey-error').hidden = true;
    try {
      return await what();
    } catch (e) {
      if (/** @type {any} */ (e)?.error === 'cancelled') return null;
      $('rkey-error').textContent =
        e instanceof Error && e.message ? e.message : t('rkey.failed', 'That did not work.');
      $('rkey-error').hidden = false;
      return null;
    }
  };
  $('rkey-show')?.addEventListener('click', async () => {
    const got = await attempt(() => api.post('/api/system/machine/key/recovery-key', {}));
    if (!got) return;
    $('rkey-code').textContent = got.recovery_key;
    $('rkey-code').hidden = false;
    $('rkey-show').hidden = true;
    $('rkey-written').hidden = false;
  });
  $('rkey-written')?.addEventListener('click', async () => {
    if (await attempt(() => api.post('/api/system/machine/key/written-down', {}))) await renderRecoveryKeyCard(mount);
  });
  $('rkey-new')?.addEventListener('click', async () => {
    if (await attempt(() => api.post('/api/system/machine/key/new-recovery-key', {})))
      await renderRecoveryKeyCard(mount);
  });
  $('rkey-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const typed = $('rkey-input').value.trim();
    const done = await attempt(() => api.post('/api/system/machine/key/unlock', { recovery_key: typed }));
    if (!done) return;
    $('rkey-status').textContent = t(
      'rkey.unlocked',
      'Opened. Kiboto is starting again; this page comes back in a moment.'
    );
    $('rkey-form').hidden = true;
  });
  return st;
}
