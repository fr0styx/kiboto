/**
 * "Show Docker details" in the Apps window (SET-25, Apps decision 1): per person, kept with their
 * account's preferences and in this browser. Off by default except for someone who manages apps and
 * has Advanced on; their account's choice wins.
 */
import { api } from '../api.js';

const STORE_NAME = 'kiboto_apps_details'; // gitleaks:allow (a storage key name)

function user() {
  return /** @type {any} */ (globalThis).kibotoUser || null;
}

/** Whether the person sees the Docker details. */
export function appsDetailsOn(u = user()) {
  const prefs = (u && (u.preferences || u.user?.preferences)) || {};
  if (typeof prefs.apps_details === 'boolean') return prefs.apps_details;
  try {
    const local = localStorage.getItem(STORE_NAME);
    if (local === '1' || local === '0') return local === '1';
  } catch {
    /* no storage: the default */
  }
  return prefs.advanced === true;
}

export function saveAppsDetails(on) {
  try {
    localStorage.setItem(STORE_NAME, on ? '1' : '0');
  } catch {
    /* the account still keeps it */
  }
  const u = user();
  if (!u) return false;
  const holder = u.preferences ? u : u.user && u.user.preferences ? u.user : u;
  holder.preferences = { ...(holder.preferences || {}), apps_details: Boolean(on) };
  api.put('/api/auth/me/preferences', { apps_details: Boolean(on) }).catch(() => {});
  return true;
}
