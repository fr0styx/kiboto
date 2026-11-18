/**
 * Storage's summary (SET-22 Storage 3, report section 4.1): one sentence from the Overview's own
 * status, so the two never disagree, the drive and pool findings with their Open buttons, when it
 * was checked, and Check again.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { formatTime } from '../format.js';
import { ROUTES } from '../router.js';
import { itemText } from './management/overview.js';

const STORAGE_ID = /^(drive|pool|storage):/;
const STORAGE_CHECKS = ['drives', 'pools', 'storage'];

/** The Overview's findings about drives, pools and space. */
export function storageItems(summary) {
  return (summary?.items || []).filter((i) => STORAGE_ID.test(i.id || '') || ['drives', 'storage'].includes(i.open));
}

/** The drives Drive Health keeps an eye on ("watch"), from the bay picture's stored verdicts:
 *  [{model, place}], where place is "Bay 2" or "M.2 slot 1". Read from memory, no drive woken. */
export function watchedDrives(chassis) {
  const out = [];
  for (const bay of chassis?.bays || []) {
    if (bay?.disk?.verdict === 'watch')
      out.push({
        model: bay.disk.model || bay.disk.dev || '',
        place: t('chassis.bay_n', 'Bay {n}', { n: (bay.slot_index ?? 0) + 1 }),
      });
  }
  for (const [i, slot] of (chassis?.nvme_slots || []).entries()) {
    if (slot?.disk?.verdict === 'watch')
      out.push({
        model: slot.disk.model || slot.disk.name || '',
        place: t('storage.m2_n', 'M.2 slot {n}', { n: i + 1 }),
      });
  }
  return out;
}

/** [sentence, tone]: what needs a look, that a check could not run, that drives are watched, or
 *  that all is fine. "All drives are fine" never stands beside a drive marked "Keep an eye on it". */
export function storageSentence(summary, watched = []) {
  const items = storageItems(summary);
  if (items.length) {
    const tone = items.some((i) => i.level === 'critical') ? 'bad' : 'warn';
    return [
      t(
        'storage.sum_look',
        '{n, plural, one {# thing on your drives needs a look} other {# things on your drives need a look}}',
        { n: items.length }
      ),
      tone,
    ];
  }
  if ((summary?.unchecked || []).some((c) => STORAGE_CHECKS.includes(c))) {
    return [t('storage.sum_unknown', "Kiboto couldn't check every drive just now."), 'warn'];
  }
  if (watched.length) {
    return [
      t(
        'storage.sum_watch',
        '{n, plural, one {All drives work. Drive Health keeps an eye on # drive.} other {All drives work. Drive Health keeps an eye on # drives.}}',
        { n: watched.length }
      ),
      'ok',
    ];
  }
  return [t('storage.sum_ok', 'All drives are fine.'), 'ok'];
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

export async function renderStorageSummary(mount = document.getElementById('storage-summary')) {
  if (!mount) return null;
  if (!mount.dataset.wired) {
    mount.dataset.wired = '1';
    mount.addEventListener('click', (e) => {
      const target = /** @type {Element} */ (e.target);
      if (target.closest('[data-sum-again]')) {
        renderStorageSummary(mount);
        return;
      }
      const open = /** @type {HTMLElement | null} */ (target.closest('[data-ov-open]'));
      if (open && ROUTES[open.dataset.ovOpen]) ROUTES[open.dataset.ovOpen]();
    });
  }
  let summary;
  let chassis = null;
  try {
    [summary, chassis] = await Promise.all([
      api.get('/api/system/status-summary'),
      api.get('/api/chassis/config').catch(() => null),
    ]);
  } catch {
    summary = { items: [], unchecked: STORAGE_CHECKS };
  }
  const watched = watchedDrives(chassis);
  const [text, tone] = storageSentence(summary, watched);
  const line = el('p', `storage-sum-line is-${tone}`);
  line.append(el('strong', '', text));
  const when = formatTime(new Date());
  line.append(' ', el('span', 'storage-sum-when', t('storage.sum_checked', 'Checked at {time}', { time: when })));
  const again = el('button', 'btn-pill-toggle', t('storage.sum_again', 'Check again'));
  again.type = 'button';
  again.dataset.sumAgain = '1';
  const parts = [line];
  const items = storageItems(summary);
  if (items.length) {
    const list = el('ul', 'storage-sum-list');
    for (const i of items) {
      const li = el('li', `storage-sum-item is-${i.level === 'critical' ? 'bad' : 'warn'}`);
      li.append(el('span', '', itemText(i)));
      if (i.open && ROUTES[i.open]) {
        const b = el('button', 'btn-pill-toggle', t('overview.open', 'Open'));
        b.type = 'button';
        b.dataset.ovOpen = i.open;
        li.append(b);
      }
      list.append(li);
    }
    parts.push(list);
  }
  if (watched.length && !items.length) {
    const list = el('ul', 'storage-sum-list');
    for (const w of watched)
      list.append(
        el('li', 'storage-sum-item is-watch', t('storage.sum_watch_item', '{model} in {place}: keep an eye on it', w))
      );
    parts.push(list);
  }
  parts.push(again);
  mount.replaceChildren(...parts);
  mount.hidden = false;
  mount.dataset.tone = tone;
  return summary;
}
