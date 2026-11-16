// "Kib can read these folders" (SET-26, AI 4; report section 4, section 1): an always-open list of
// folders by name, each with a real tick box, its state in words, and a menu with words. A second
// list, "Never read", holds the folders Kib was told to forget. It replaces the dropdown, the chips
// with 🔄 ✕ 🗑, "RAG Checked" / "Click to Add" and the device names ("💤 Standby (sdX)").
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';

/** The last part of a path: what people call the folder. */
export function folderName(path) {
  const parts = String(path || '').replace(/\/+$/, '').split('/').filter(Boolean);
  return parts.length ? parts[parts.length - 1] : String(path || '');
}

const inside = (path, folder) => path === folder || String(path || '').startsWith(`${folder.replace(/\/+$/, '')}/`);

/**
 * One folder's state in words: reading, waiting for its drive, or up to date. Only for folders Kib
 * reads; the others say nothing.
 * @param {string} path
 * @param {any} res the status (GET /api/ai/status)
 * @param {{ in_standby?: boolean } | undefined} info the folder as the server found it
 */
export function folderState(path, res, info) {
  const sync = res?.sync_progress || {};
  const running = String(sync.state || '').toLowerCase() === 'running';
  if (running && (inside(String(sync.current_path || ''), path) || (sync.target_paths || []).some((p) => inside(String(p), path)))) {
    return { key: 'reading', text: t('kibf.reading', 'Reading') };
  }
  const queued = (res?.standby_guard?.deferred_queue || []).some((q) => inside(String(q?.path || q || ''), path));
  if (queued || info?.in_standby) return { key: 'asleep', text: t('kibf.asleep', 'Waiting for a drive to wake') };
  return { key: 'ok', text: t('kibf.up_to_date', 'Up to date') };
}

/**
 * Every folder Kib may be given: the ones the server found and the ones already chosen.
 * @param {any} res
 * @returns {{ path: string, chosen: boolean, info: any }[]}
 */
export function folderRows(res = {}) {
  const chosen = (res.watched_paths || []).map(String);
  const found = Array.isArray(res.available_folders) ? res.available_folders : [];
  const rows = found.map((f) => ({ path: String(f.path), chosen: chosen.includes(String(f.path)), info: f }));
  for (const p of chosen) if (!rows.some((r) => r.path === p)) rows.push({ path: p, chosen: true, info: undefined });
  return rows;
}

/** The list as markup: tick box, name, state, menu; then "Never read" and "Add a folder…". */
export function kibFoldersHtml(res = {}) {
  const rows = folderRows(res);
  const never = (res.excluded_paths || []).map(String);
  const list = rows.length
    ? rows.map((r, n) => {
      const id = `kibf-${n}`;
      const state = r.chosen ? folderState(r.path, res, r.info) : null;
      const menu = r.chosen
        ? `<details class="kibf-menu"><summary class="btn-pill-toggle is-small" aria-label="${escapeHtml(t('kibf.menu_for', 'What Kib does with {name}', { name: folderName(r.path) }))}">⋯</summary>
            <div class="kibf-menu-list">
              <button type="button" data-kibf-act="read" data-path="${escapeHtml(r.path)}">${escapeHtml(t('kibf.read_now', 'Read now'))}</button>
              <button type="button" data-kibf-act="stop" data-path="${escapeHtml(r.path)}">${escapeHtml(t('kibf.stop', 'Stop reading (Kib keeps what it knows)'))}</button>
              <button type="button" data-kibf-act="forget" data-path="${escapeHtml(r.path)}">${escapeHtml(t('kibf.forget', 'Stop reading and forget this folder (your files stay)'))}</button>
            </div></details>`
        : '';
      return `<li class="kibf-row${r.chosen ? ' is-chosen' : ''}">
          <input type="checkbox" id="${id}" data-kibf-act="tick" data-path="${escapeHtml(r.path)}"${r.chosen ? ' checked' : ''}>
          <label for="${id}" class="kibf-name"><strong>${escapeHtml(folderName(r.path))}</strong><span class="kibf-path">${escapeHtml(r.path)}</span></label>
          ${state ? `<span class="kibf-state is-${state.key}">${escapeHtml(state.text)}</span>` : ''}
          ${menu}
        </li>`;
    }).join('')
    : `<li class="kibf-empty">${escapeHtml(t('kibf.none_found', 'No folders found yet. Add one below.'))}</li>`;
  const neverHtml = never.length
    ? `<h4 class="kibf-sub">${escapeHtml(t('kibf.never', 'Never read'))}</h4>
       <ul class="kibf-list">${never.map((p) => `<li class="kibf-row"><span class="kibf-name"><strong>${escapeHtml(folderName(p))}</strong><span class="kibf-path">${escapeHtml(p)}</span></span>
         <button type="button" class="btn-pill-toggle is-small" data-kibf-act="unforget" data-path="${escapeHtml(p)}">${escapeHtml(t('kibf.remove', 'Remove'))}</button></li>`).join('')}</ul>`
    : '';
  return `<p class="kibf-intro">${escapeHtml(t('kibf.intro', 'Tick the folders Kib may read. If a drive is asleep, Kib reads the folder the next time the drive is awake.'))}</p>
    <ul class="kibf-list">${list}</ul>
    <button type="button" class="btn-pill-toggle" data-kibf-act="add">${escapeHtml(t('kibf.add', 'Add a folder…'))}</button>
    ${neverHtml}`;
}

/**
 * Draws the list and wires it to the page's actions.
 * @param {HTMLElement | null} mount
 * @param {any} res
 * @param {Record<string, (path: string, on?: boolean) => unknown>} actions tick, read, stop, forget, unforget, add
 */
export function renderKibFolders(mount, res, actions = {}) {
  if (!mount) return;
  mount.innerHTML = kibFoldersHtml(res);
  mount.querySelectorAll('[data-kibf-act]').forEach((el) => {
    const node = /** @type {HTMLInputElement} */ (el);
    const act = node.dataset.kibfAct || '';
    const path = node.dataset.path || '';
    const run = actions[act];
    if (typeof run !== 'function') return;
    if (act === 'tick') node.addEventListener('change', () => run(path, node.checked));
    else node.addEventListener('click', () => {
      node.closest('details')?.removeAttribute('open');
      run(path);
    });
  });
}
