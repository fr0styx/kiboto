/**
 * Installable app and phone share sheet (M1).
 *
 * Registers the service worker, and after files arrive from the share sheet
 * (the worker saves them to the Inbox and comes back to /?shared=N) says how many.
 */
import { t } from './i18n.js';
import { showToast } from './toast.js';
import { openRoute } from './router.js';

export function sharedResultMessage(params) {
  const shared = params.get('shared');
  if (shared === null) return null;
  if (shared === 'login') {
    return { text: t('pwa.share_login', 'Sign in, then share the files again.'), type: 'warn' };
  }
  if (shared === 'error') {
    return { text: t('pwa.share_error', 'The shared files could not be read.'), type: 'error' };
  }
  const saved = parseInt(shared, 10) || 0;
  const failed = parseInt(params.get('failed') || '0', 10) || 0;
  if (failed) {
    return {
      text: t('pwa.share_partial', '{saved} saved to your Inbox, {failed} failed.', { saved, failed }),
      type: 'warn',
    };
  }
  return { text: t('pwa.share_saved', '{saved} saved to your Inbox folder.', { saved }), type: 'success' };
}

/**
 * A shortcut or link opened while the installed app runs comes to this window (the manifest's
 * launch_handler, focus-existing) and opens its place. The first launch is the one that loaded
 * this page: the router opens its link already.
 */
export function watchLaunches(win = window, open = openRoute) {
  const queue = /** @type {any} */ (win).launchQueue;
  if (!queue || typeof queue.setConsumer !== 'function') return false;
  let first = true;
  queue.setConsumer((params) => {
    if (first) {
      first = false;
      return;
    }
    try {
      const url = new URL(params.targetURL);
      if (url.hash && open(url.hash)) win.history.replaceState(null, '', url.pathname + url.search + url.hash);
    } catch (e) {
      console.warn('[Kiboto] launch not opened:', e);
    }
  });
  return true;
}

let _badge = -1;
/** The unread count on the installed app's icon (nothing in a browser tab or where unsupported). */
export function setAppBadge(count, nav = /** @type {any} */ (globalThis.navigator)) {
  const n = Math.max(0, count | 0);
  if (!nav || n === _badge) return;
  _badge = n;
  try {
    const done = n > 0 ? nav.setAppBadge?.(n) : nav.clearAppBadge?.();
    done?.catch?.(() => {});
  } catch {
    /* not supported here */
  }
}

export function initPwa(win = window) {
  watchLaunches(win);
  const nav = win.navigator;
  if (nav && 'serviceWorker' in nav && win.location.protocol !== 'file:') {
    nav.serviceWorker.register('/sw.js').catch((e) => console.warn('Service worker not registered:', e));
  }
  const params = new URLSearchParams(win.location.search);
  const msg = sharedResultMessage(params);
  if (msg) {
    showToast(msg.text, msg.type);
    params.delete('shared');
    params.delete('failed');
    const q = params.toString();
    win.history.replaceState(null, '', win.location.pathname + (q ? `?${q}` : '') + win.location.hash);
  }
}
