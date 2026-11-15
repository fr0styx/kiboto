// Who can open each shared folder, as one sentence on its card (SET-22, Shares 2): "Anna and Ben can
// change it. Mia can view it." Administrators are in it, as they really can. Where the host runs the
// network shares (Unraid, TrueNAS), the sentence says it is about Files and that the host decides
// for the network.
import { api } from '../api.js';
import { t } from '../i18n.js';
import { currentLocale } from '../format.js';

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
      line = document.createElement('p');
      line.className = 'share-who';
      card.querySelector('.share-card-header')?.after(line);
    }
    line.textContent = whoSentence(share.people || [], host);
  }
  return who;
}
