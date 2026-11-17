// "Your folders and their copies" on Backup (Backup 5): each shared folder with the copies outside
// this NAS that hold it, "No copy outside this NAS" where none does, and a way to say that a folder
// is left out on purpose (a scratch or download folder), so it stops counting as unprotected.
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { formatDateTime } from '../format.js';

/** One folder's state in words. */
export function folderLine(f) {
  const names = (list) => list.map((c) => c.name).join(', ');
  if (f.left_out) return { key: 'left', text: t('bkf.left_out', 'Left out on purpose') };
  if ((f.copies || []).length) {
    const last = Math.max(...f.copies.map((c) => Number(c.last_ok || 0)));
    return { key: 'ok', text: last ? t('bkf.copied_when', 'Copied by {names}, last {when}', { names: names(f.copies), when: formatDateTime(last * 1000) }) : t('bkf.copied', 'Copied by {names}', { names: names(f.copies) }) };
  }
  if ((f.partly || []).length) return { key: 'part', text: t('bkf.partly', 'Partly copied by {names}', { names: names(f.partly) }) };
  return { key: 'none', text: t('bkf.none', 'No copy outside this NAS') };
}

/** The folded section. */
export function foldersHtml(folders, canChange) {
  const missing = folders.filter((f) => folderLine(f).key === 'none').length;
  const summary = missing
    ? t('bkf.summary_missing', '{n, plural, one {# folder has} other {# folders have}} no copy outside this NAS', { n: missing })
    : t('bkf.summary_ok', 'Every folder has a copy outside this NAS, or is left out on purpose');
  const rows = folders.map((f) => {
    const line = folderLine(f);
    const box = canChange && (line.key === 'none' || line.key === 'left')
      ? `<label class="bkf-left"><input type="checkbox" data-bkf-left="${escapeHtml(f.name)}"${f.left_out ? ' checked' : ''}> ${escapeHtml(t('bkf.leave_out', 'Leave out on purpose'))}</label>`
      : '';
    return `<li class="bkf-row is-${line.key}"><strong>${escapeHtml(f.name)}</strong><span>${escapeHtml(line.text)}</span>${box}</li>`;
  }).join('');
  return `<details class="bkf"${missing ? ' open' : ''}><summary>${escapeHtml(t('bkf.title', 'Your folders and their copies'))}: ${escapeHtml(summary)}</summary><ul class="bkf-list">${rows}</ul></details>`;
}

/**
 * Draws the section after the verdict.
 * @param {HTMLElement | null} after the verdict's mount
 * @param {boolean} [canChange] whether this person may change backups
 */
export async function renderFolders(after, canChange = true) {
  if (!after) return;
  let data;
  try {
    data = await api.get('/api/system/protection/folders');
  } catch {
    return; // not someone who may see backups
  }
  const folders = Array.isArray(data?.folders) ? data.folders : [];
  let box = /** @type {HTMLElement | null} */ (after.parentElement?.querySelector('#backup-folders') || null);
  if (!folders.length) {
    box?.remove();
    return;
  }
  if (!box) {
    box = document.createElement('div');
    box.id = 'backup-folders';
    after.insertAdjacentElement('afterend', box);
  }
  box.innerHTML = foldersHtml(folders, canChange);
  box.querySelectorAll('[data-bkf-left]').forEach((el) => {
    const input = /** @type {HTMLInputElement} */ (el);
    input.addEventListener('change', async () => {
      try {
        await api.put('/api/system/protection/folders/left-out', { name: input.dataset.bkfLeft, left_out: input.checked });
      } catch (err) {
        showToast(/** @type {Error} */ (err).message, 'error');
      }
      await renderFolders(after, canChange);
    });
  });
}
