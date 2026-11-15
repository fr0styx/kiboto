// Who can open each shared folder, as one sentence on its card (SET-22, Shares 2): "Anna and Ben can
// change it. Mia can view it." Administrators are in it, as they really can. Where the host runs the
// network shares (Unraid, TrueNAS), the sentence says it is about Files and that the host decides
// for the network.
import { api } from '../api.js';
import { t } from '../i18n.js';
import { currentLocale } from '../format.js';
import { escapeHtml } from '../utils.js';
import { showToast } from '../toast.js';

const MANY = 4;

/** "Anna, Ben and Mia" in the page's language. */
export function nameList(names, locale = currentLocale()) {
  try {
    return new Intl.ListFormat(locale, { style: 'long', type: 'conjunction' }).format(names);
  } catch {
    return names.join(', ');
  }
}

/** The sentence for one folder's people. */
export function whoSentence(people, host = '', locale = currentLocale()) {
  const names = (level) => people.filter((p) => p.level === level).map((p) => p.name || p.username);
  const write = names('write');
  const read = names('read');
  const said = [];
  if (write.length >= MANY) said.push(t('who.change_many', '{n} people can change it.', { n: write.length }));
  else if (write.length > 1) said.push(t('who.change', '{names} can change it.', { names: nameList(write, locale) }));
  else if (write.length) said.push(t('who.change_one', '{names} can change it.', { names: write[0] }));
  if (read.length >= MANY) said.push(t('who.view_many', '{n} people can view it.', { n: read.length }));
  else if (read.length > 1) said.push(t('who.view', '{names} can view it.', { names: nameList(read, locale) }));
  else if (read.length) said.push(t('who.view_one', '{names} can view it.', { names: read[0] }));
  const text = said.length ? said.join(' ') : t('who.nobody', 'Nobody can open it yet.');
  return host ? t('who.host', 'In Files: {text} Over the network: {host} decides.', { text, host }) : text;
}

const LEVEL_WORDS = () => ({ none: t('who.l_none', 'No access'), read: t('who.l_read', 'Can view'), write: t('who.l_write', 'Can view and change') });

/** The window's rows: administrators as they are, everyone else with a choice; a guest views at most. */
export function whoRowsHtml(people) {
  const words = LEVEL_WORDS();
  return people
    .map((p) => {
      const name = escapeHtml(p.name || p.username);
      if (p.admin) return `<li class="who-row"><span>${name}</span><span class="who-fixed">${escapeHtml(t('who.l_admin', 'Can view and change (administrator)'))}</span></li>`;
      const levels = p.role === 'guest' ? ['none', 'read'] : ['none', 'read', 'write'];
      const value = levels.includes(p.level) ? p.level : 'read';
      return `<li class="who-row"><label for="who-${escapeHtml(p.username)}">${name}</label><select id="who-${escapeHtml(p.username)}" class="tz-select-input" data-who-user="${escapeHtml(p.username)}">${levels
        .map((l) => `<option value="${l}"${l === value ? ' selected' : ''}>${escapeHtml(words[l])}</option>`)
        .join('')}</select></li>`;
    })
    .join('');
}

/** Every share's saved entry, with this one's people as chosen: the PUT replaces the list whole. */
export function savedWith(access, share, chosen) {
  const shares = {};
  for (const s of access.shares || []) shares[s.name] = { users: { ...(s.users || {}) }, ...(s.default ? { default: s.default } : {}) };
  shares[share] = { ...(shares[share] || {}), users: { ...((shares[share] || {}).users || {}), ...chosen } };
  return { shares };
}

/** The window for one folder; resolves true when saved. */
export async function openWhoWindow(share, onSaved = null) {
  let access;
  let who;
  try {
    [access, who] = await Promise.all([api.get('/api/storage/share-access'), api.get('/api/storage/share-access/who')]);
  } catch (err) {
    showToast(/** @type {Error} */ (err).message, 'error');
    return false;
  }
  const people = ((who.shares || []).find((s) => s.name === share) || {}).people || [];
  document.getElementById('who-window')?.remove();
  const dlg = document.createElement('dialog');
  dlg.id = 'who-window';
  dlg.className = 'who-window';
  dlg.setAttribute('aria-labelledby', 'who-window-title');
  dlg.innerHTML = `<h2 id="who-window-title" class="account-h">${escapeHtml(t('who.title', 'Who can open "{share}"', { share }))}</h2>
    <p class="who-note">${escapeHtml(who.host ? t('who.note_host', 'This applies to Files. Over the network, the host decides.') : t('who.note', 'One list for Files and the network.'))}</p>
    <ul class="who-rows">${whoRowsHtml(people)}</ul>
    <div class="who-actions"><button type="button" class="btn-pill-toggle" data-who-close>${escapeHtml(t('common.cancel', 'Cancel'))}</button><button type="button" class="btn-pill-toggle is-primary" data-who-save>${escapeHtml(t('common.save', 'Save'))}</button></div>`;
  document.body.appendChild(dlg);
  return new Promise((resolve) => {
    const done = (saved) => {
      dlg.close?.();
      dlg.remove();
      resolve(saved);
    };
    dlg.addEventListener('cancel', () => done(false));
    dlg.onclick = async (e) => {
      const b = /** @type {HTMLElement} */ (e.target).closest('button');
      if (!b) return;
      if (b.hasAttribute('data-who-close')) done(false);
      else if (b.hasAttribute('data-who-save')) {
        const chosen = Object.fromEntries([...dlg.querySelectorAll('select[data-who-user]')].map((s) => [/** @type {HTMLElement} */ (s).dataset.whoUser, /** @type {HTMLSelectElement} */ (s).value]));
        try {
          await api.put('/api/storage/share-access', savedWith(access, share, chosen));
          showToast(t('who.saved', 'Saved. "{share}" opens for the people you chose.', { share }), 'success');
          if (onSaved) onSaved();
          done(true);
        } catch (err) {
          showToast(/** @type {Error} */ (err).message, 'error');
        }
      }
    };
    if (typeof dlg.showModal === 'function') dlg.showModal();
    else dlg.setAttribute('open', '');
    /** @type {HTMLElement | null} */ (dlg.querySelector('select, [data-who-close]'))?.focus();
  });
}

/** Puts the sentence on each card of the grid; a refusal (not someone who manages shares) adds nothing. */
export async function fillWhoLines(grid, names = {}) {
  if (!grid) return null;
  let who;
  try {
    who = await api.get('/api/storage/share-access/who');
  } catch {
    return null;
  }
  const host = who.host ? names[who.host] || who.host : '';
  for (const share of who.shares || []) {
    const card = [...grid.querySelectorAll('[data-share]')].find((c) => /** @type {HTMLElement} */ (c).dataset.share === share.name);
    if (!card) continue;
    let line = card.querySelector('.share-who');
    if (!line) {
      line = document.createElement('div');
      line.className = 'share-who';
      line.innerHTML = '<span class="share-who-text"></span> <button type="button" class="btn-pill-toggle is-small" data-who-open></button>';
      card.querySelector('.share-card-header')?.after(line);
      /** @type {HTMLElement} */ (line.querySelector('[data-who-open]')).onclick = () => openWhoWindow(share.name, () => fillWhoLines(grid, names));
    }
    /** @type {HTMLElement} */ (line.querySelector('.share-who-text')).textContent = whoSentence(share.people || [], host);
    /** @type {HTMLElement} */ (line.querySelector('[data-who-open]')).textContent = t('who.open', 'Who can open it');
  }
  return who;
}
