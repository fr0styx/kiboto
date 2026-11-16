/**
 * The File Explorer's view, sort and "Show hidden files" follow the person (SET-28 Files 4): kept in
 * their account's preferences, with this browser's copy as the fallback. On their first sign-in the
 * browser's old values win once and are saved to the account.
 */
import { api } from '../api.js';

/** The signed-in account (route-access.js keeps it here; importing session.js pulls in more than this needs). */
export function currentUser() {
  return /** @type {any} */ (globalThis).kibotoUser || null;
}

const VIEWS = ['list', 'compact', 'icon'];
const SORTS = ['name', 'size', 'type', 'mtime'];

/** The person's saved File Explorer view, or null when they have none yet. */
export function personFilesView(user = currentUser()) {
  const prefs = (user && (user.preferences || user.user?.preferences)) || {};
  return prefs.files && typeof prefs.files === 'object' ? prefs.files : null;
}

function readLocal() {
  try {
    return {
      view: localStorage.getItem('kiboto_fm_view_mode') || 'list',
      sort: localStorage.getItem('kiboto_fm_sort') || 'name',
      sort_dir: localStorage.getItem('kiboto_fm_sort_dir') || 'asc',
      hidden: localStorage.getItem('kiboto_fm_hidden') === '1',
    };
  } catch {
    return {};
  }
}

/** What a new window starts with; `seed` when the account has nothing yet (save the browser's once). */
export function startingView(person = personFilesView(), local = readLocal()) {
  const src = person || local || {};
  return {
    view: VIEWS.includes(src.view) ? src.view : 'list',
    sort: SORTS.includes(src.sort) ? src.sort : 'name',
    sort_dir: src.sort_dir === 'desc' ? 'desc' : 'asc',
    hidden: Boolean(src.hidden),
    seed: !person,
  };
}

let _timer = null;

/** Saves the view in this browser at once and in the account a moment later. */
export function saveFilesView(v, wait = 600) {
  const files = { view: v.view, sort: v.sort, sort_dir: v.sort_dir, hidden: Boolean(v.hidden) };
  try {
    localStorage.setItem('kiboto_fm_view_mode', files.view);
    localStorage.setItem('kiboto_fm_sort', files.sort);
    localStorage.setItem('kiboto_fm_sort_dir', files.sort_dir);
    localStorage.setItem('kiboto_fm_hidden', files.hidden ? '1' : '0');
  } catch {
    /* a private window: the account still keeps it */
  }
  const user = currentUser();
  if (!user) return null;
  const holder = user.preferences ? user : user.user && user.user.preferences ? user.user : user;
  holder.preferences = { ...(holder.preferences || {}), files };
  clearTimeout(_timer);
  _timer = setTimeout(() => api.put('/api/auth/me/preferences', { files }).catch(() => {}), wait);
  return files;
}

/** The entries to list: hidden files (a name starting with a dot) only when asked for. */
export function visibleEntries(entries, showHidden) {
  const all = entries || [];
  if (showHidden) return { list: all, hidden: 0 };
  const list = all.filter((f) => f.name === '..' || !String(f.name || '').startsWith('.'));
  return { list, hidden: all.length - list.length };
}
