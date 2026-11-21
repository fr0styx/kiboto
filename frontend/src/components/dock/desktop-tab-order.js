// While a window is open, the desktop behind it (icons, widgets, the Getting started card) is left
// out of the Tab key's walk: it cannot be seen there, and 40 or more stops went to it before the
// window's own. Its focusable elements get tabindex="-1" and their own value back when the last
// window closes or is minimised. Clicks still reach the desktop beside a window: no `inert`.

const ROOTS = ['#desktop-icons-container', '#desktop-widgets-container', '.getting-started-card'];
const FOCUSABLE = 'a[href], button, input, select, textarea, summary, [tabindex], [contenteditable="true"]';
const KEPT = 'data-kb-tab'; // the element's own tabindex ("" when it had none)
let watcher = null;

/** Whether one of the dock's windows is open and showing. */
export function anyWindowShown(windows) {
  return Object.values(windows || {}).some(
    (w) => w && w.el && w.el.isConnected && !w.minimized && !w.closed && w.el.style.display !== 'none'
  );
}

function roots() {
  return ROOTS.flatMap((sel) => [...document.querySelectorAll(sel)]);
}

function leaveOut(root) {
  const all = root.matches(FOCUSABLE)
    ? [root, ...root.querySelectorAll(FOCUSABLE)]
    : [...root.querySelectorAll(FOCUSABLE)];
  for (const el of all) {
    if (!el.hasAttribute(KEPT)) el.setAttribute(KEPT, el.getAttribute('tabindex') ?? '');
    el.setAttribute('tabindex', '-1');
  }
}

function giveBack(root) {
  const all = root.hasAttribute(KEPT)
    ? [root, ...root.querySelectorAll(`[${KEPT}]`)]
    : [...root.querySelectorAll(`[${KEPT}]`)];
  for (const el of all) {
    const own = el.getAttribute(KEPT);
    if (own) el.setAttribute('tabindex', own);
    else el.removeAttribute('tabindex');
    el.removeAttribute(KEPT);
  }
}

/** Called whenever the dock redraws (a window opened, closed, minimised or came back). */
export function syncDesktopTabOrder(windows) {
  const shown = anyWindowShown(windows);
  const found = roots();
  found.forEach(shown ? leaveOut : giveBack);
  if (shown && !watcher && typeof MutationObserver !== 'undefined') {
    // widgets redraw themselves: what they add while a window is open stays out too
    watcher = new MutationObserver(() => roots().forEach(leaveOut));
    found.forEach((root) => watcher.observe(root, { childList: true, subtree: true }));
  } else if (!shown && watcher) {
    watcher.disconnect();
    watcher = null;
  }
}
