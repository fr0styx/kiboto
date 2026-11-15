// Get something back (SET-21 stage 2, Backup report section 4.2): one door for restore. Three
// buttons, and the folder and day are picked right here on the page (no window over a window):
// "A file or folder" opens that day's files with "Restore a copy" first; "A whole folder as it was"
// is the safe rollback (how it is now is kept first); "Everything" is the restore window.
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { formatDateTime } from '../format.js';

/** The folder a snapshot belongs to: the part before "@" (Kiboto's naming), else its path's last part. */
export function folderOf(snap) {
  const name = String(snap.name || '');
  if (name.includes('@')) return name.slice(0, name.indexOf('@'));
  const path = String(snap.path || '').replace(/\/+$/, '');
  return path.slice(path.lastIndexOf('/') + 1) || name;
}

/** {folder: [snapshots newest first]}; a whole-folder rollback only takes Kiboto-named ones. */
export function groupSnapshots(snaps, wholeFolder = false) {
  /** @type {Record<string, any[]>} */
  const out = {};
  for (const s of snaps || []) {
    if (wholeFolder && !String(s.name || '').includes('@')) continue;
    (out[folderOf(s)] ||= []).push(s);
  }
  for (const list of Object.values(out)) list.sort((a, b) => Number(b.created_at || 0) - Number(a.created_at || 0));
  return out;
}

export function doorHtml() {
  const b = (act, label, line) =>
    `<button type="button" class="rd-choice" data-rd="${act}"><span class="rd-choice-name">${escapeHtml(label)}</span><span class="rd-choice-line">${escapeHtml(line)}</span></button>`;
  return `<p class="rd-bin">${escapeHtml(t('rd.bin', 'Deleted it just now? Look in the Recycle Bin first.'))} <button type="button" class="rd-link" data-rd="bin">${escapeHtml(t('rd.open_bin', 'Open the Recycle Bin'))}</button></p>
    <div class="rd-choices">
      ${b('file', t('rd.file', 'A file or folder'), t('rd.file_d', 'Pick the folder and the day; a copy comes back next to the current one.'))}
      ${b('folder', t('rd.folder', 'A whole folder as it was'), t('rd.folder_d', 'The folder goes back to that day. How it is now is kept first.'))}
      ${b('all', t('rd.all', 'Everything, onto this Kiboto'), t('rd.all_d', 'From an off-site backup or a recovery kit, after a disk or the whole box was lost.'))}
    </div>
    <div class="rd-pick" data-rd-pick hidden></div>`;
}

/** Step 1: which folder. */
export function foldersHtml(groups, mode) {
  const names = Object.keys(groups).sort((a, b) => a.localeCompare(b));
  if (!names.length) {
    return `<p class="rd-none">${escapeHtml(mode === 'folder' ? t('rd.none_folder', 'No folder can go back to an earlier day yet: a folder needs scheduled earlier versions first (further down this page).') : t('rd.none', 'No earlier versions on this Kiboto yet.'))}</p>
      <p class="rd-none">${escapeHtml(t('rd.offsite_hint', 'An off-site backup can still bring files back: Browse on its row.'))} <button type="button" class="rd-link" data-rd="offsite">${escapeHtml(t('rd.to_offsite', 'Go to off-site backups'))}</button></p>`;
  }
  return `<p class="rd-step" id="rd-step-title">${escapeHtml(t('rd.which_folder', 'Which folder?'))}</p>
    <ul class="rd-list" aria-labelledby="rd-step-title">${names
      .map((n) => `<li><button type="button" class="rd-item" data-rd-folder="${escapeHtml(n)}">${escapeHtml(n)} <span class="rd-item-meta">${escapeHtml(t('rd.newest', 'newest {when}', { when: formatDateTime(groups[n][0].created_at) }))}</span></button></li>`)
      .join('')}</ul>`;
}

/** Step 2: which day. */
export function daysHtml(folder, snaps) {
  return `<p class="rd-step" id="rd-step-title"><button type="button" class="rd-link" data-rd-back>${escapeHtml(t('rd.back', 'Back'))}</button> ${escapeHtml(t('rd.which_day', '{folder}: which day?', { folder }))}</p>
    <ul class="rd-list" aria-labelledby="rd-step-title">${snaps
      .map((s) => `<li><button type="button" class="rd-item" data-rd-snap="${escapeHtml(s.name)}">${escapeHtml(formatDateTime(s.created_at))}</button></li>`)
      .join('')}</ul>`;
}

/** Fills the mount; returns the state for tests. */
export function installRestoreDoor(mount, deps = {}) {
  if (!mount) return null;
  const st = { mode: '', groups: /** @type {Record<string, any[]>} */ ({}) };
  mount.innerHTML = doorHtml();
  const pick = /** @type {HTMLElement} */ (mount.querySelector('[data-rd-pick]'));
  const open = async (mode) => {
    st.mode = mode;
    mount.querySelectorAll('[data-rd]').forEach((b) => b.setAttribute('aria-pressed', String(b.getAttribute('data-rd') === mode)));
    pick.hidden = false;
    pick.textContent = t('rd.looking', 'Looking for earlier versions…');
    /** @type {any[]} */
    let snaps;
    try {
      snaps = (await api.get('/api/backup/snapshots'))?.snapshots || [];
    } catch {
      snaps = [];
    }
    st.groups = groupSnapshots(snaps, mode === 'folder');
    pick.innerHTML = foldersHtml(st.groups, mode);
    /** @type {HTMLElement | null} */ (pick.querySelector('button'))?.focus();
  };
  mount.onclick = async (e) => {
    const el = /** @type {HTMLElement} */ (e.target).closest('button');
    if (!el) return;
    const act = el.getAttribute('data-rd');
    if (act === 'bin') (deps.openBin || /** @type {any} */ (window).openRecycleBin)?.();
    else if (act === 'all') {
      const m = await (deps.restoreBox || (() => import('./restore-box.js')))();
      m.openRestoreBox();
    } else if (act === 'offsite') document.getElementById('offsite-title')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    else if (act === 'file' || act === 'folder') await open(act);
    else if (el.hasAttribute('data-rd-back')) {
      pick.innerHTML = foldersHtml(st.groups, st.mode);
      /** @type {HTMLElement | null} */ (pick.querySelector('button'))?.focus();
    } else if (el.dataset.rdFolder) {
      pick.innerHTML = daysHtml(el.dataset.rdFolder, st.groups[el.dataset.rdFolder] || []);
      /** @type {HTMLElement | null} */ (pick.querySelector('[data-rd-snap]'))?.focus();
    } else if (el.dataset.rdSnap) {
      const m = await (deps.snapshots || (() => import('./snapshot-browser.js')))();
      if (st.mode === 'folder') m.rollbackShare(el.dataset.rdSnap);
      else m.openSnapshotBrowser(el.dataset.rdSnap);
    }
  };
  return st;
}
