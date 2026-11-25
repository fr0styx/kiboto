// The Hardware panel behind the top-bar button (owner, 25 Nov): the Hardware page's own sections,
// moved into a panel that slides in, with a tab for each kind of hardware this machine has. They are
// the same elements as on the page (one set of controls, so the two can never disagree), and they go
// back to the page when the panel closes. On a phone the panel covers the screen.
import '../styles/hardware-drawer.css'; // loads with the panel, not on every page
import { t } from '../i18n.js';
import { ensureManagementDom } from '../management-dom.js';

/** Each tab and the Hardware page sections it shows (management-window.html). */
export const TABS = {
  cooling: { label: ['hwd.tab_cooling', 'Cooling and fans'], panes: ['mgmt-pane-unraid', 'mgmt-pane-hardware-fans'] },
  lights: { label: ['hwd.tab_lights', 'Lights'], panes: ['mgmt-pane-hardware-led'] },
  screen: { label: ['hwd.tab_screen', 'Front screen'], panes: ['mgmt-pane-hardware-lcd'] },
  copies: { label: ['hwd.tab_copies', 'Card copies'], panes: ['mgmt-pane-hardware-copy', 'mgmt-pane-copy'] },
};

let _open = null; // { tabs, active, moved: [{ pane, marker }], returnFocus, onKey }

export function isOpen() {
  return Boolean(_open);
}

function el(tag, props = {}, kids = []) {
  const n = document.createElement(tag);
  Object.assign(n, props);
  for (const k of kids) n.append(k);
  return n;
}

function shell() {
  let drawer = document.getElementById('hw-drawer');
  if (drawer) return drawer;
  const backdrop = el('div', { id: 'hw-drawer-backdrop', className: 'hwd-backdrop' });
  backdrop.addEventListener('click', () => closeHardwareDrawer());
  const sub = el('div', { className: 'drawer-sub hwd-sub' }, [
    el('span', { id: 'hwd-nas', textContent: nasName() }),
    ' • ',
    el('span', { textContent: t('hwd.title', 'Hardware') }),
  ]);
  const title = el('h2', { id: 'hwd-title', className: 'drawer-title', textContent: t('hwd.title', 'Hardware') });
  const desc = el('p', { id: 'hwd-desc', className: 'drawer-subdesc' });
  const close = el('button', { type: 'button', className: 'btn-icon hwd-close', textContent: '✕' });
  close.setAttribute('aria-label', t('hwd.close', 'Close'));
  close.addEventListener('click', () => closeHardwareDrawer());
  const tablist = el('div', { className: 'drawer-tabs-nav hwd-tabs' });
  tablist.setAttribute('role', 'tablist');
  tablist.setAttribute('aria-labelledby', 'hwd-title');
  tablist.addEventListener('keydown', onTabKeys);
  const body = el('div', { id: 'hwd-panel', className: 'hwd-body' });
  body.setAttribute('role', 'tabpanel');
  body.tabIndex = -1;
  drawer = el('aside', { id: 'hw-drawer', className: 'hwd' }, [
    el('div', { className: 'drawer-header hwd-head' }, [el('div', {}, [sub, title, desc]), close]),
    tablist,
    body,
  ]);
  drawer.setAttribute('role', 'dialog');
  drawer.setAttribute('aria-modal', 'true');
  drawer.setAttribute('aria-labelledby', 'hwd-title');
  drawer.hidden = true;
  backdrop.hidden = true;
  document.body.append(backdrop, drawer);
  return drawer;
}

/** The server's name, as the old drawer showed it; "NAS" until it is known. */
function nasName() {
  const known = document.getElementById('drawer-nas-name');
  return (known && known.textContent.trim()) || 'NAS';
}

function showTab(id) {
  if (!_open || !_open.tabs.includes(id)) return;
  _open.active = id;
  const drawer = document.getElementById('hw-drawer');
  // the header says what the tab is, in the words of its first section (whose own heading is hidden)
  const first = document.getElementById(TABS[id].panes[0]);
  document.getElementById('hwd-title').textContent = t(...TABS[id].label);
  const words = first && first.querySelector('.mgmt-card-intro-desc');
  document.getElementById('hwd-desc').textContent = words ? words.textContent.trim() : '';
  document.getElementById('hwd-nas').textContent = nasName();
  for (const btn of drawer.querySelectorAll('.hwd-tab')) {
    const on = btn.dataset.tab === id;
    btn.setAttribute('aria-selected', String(on));
    btn.tabIndex = on ? 0 : -1;
    if (on) document.getElementById('hwd-panel').setAttribute('aria-labelledby', btn.id);
  }
  for (const group of drawer.querySelectorAll('.hwd-group')) group.hidden = group.dataset.tab !== id;
}

function onTabKeys(e) {
  if (!_open || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
  const tabs = _open.tabs;
  const i = tabs.indexOf(_open.active);
  const next =
    e.key === 'Home'
      ? 0
      : e.key === 'End'
        ? tabs.length - 1
        : (i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
  e.preventDefault();
  showTab(tabs[next]);
  document.getElementById(`hwd-tab-${tabs[next]}`)?.focus();
}

function focusables(root) {
  return [...root.querySelectorAll('button, [href], input, select, textarea, [tabindex]')].filter(
    (n) => !n.disabled && n.tabIndex >= 0 && !n.closest('[hidden], [inert]') && n.getClientRects().length
  );
}

function onKey(e) {
  if (!_open) return;
  const drawer = document.getElementById('hw-drawer');
  if (e.key === 'Escape') {
    // the panel is on top: Escape closes it and nothing behind it
    e.preventDefault();
    e.stopImmediatePropagation();
    closeHardwareDrawer();
  } else if (e.key === 'Tab') {
    const list = focusables(drawer);
    if (!list.length) return;
    const first = list[0];
    const last = list[list.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (document.activeElement === last || !drawer.contains(document.activeElement))) {
      e.preventDefault();
      first.focus();
    }
  }
}

function pageNote() {
  const page = document.getElementById('mgmt-sec-hardware');
  if (!page || document.getElementById('hwd-page-note')) return;
  const show = el('button', {
    type: 'button',
    className: 'btn-pill-toggle is-small',
    textContent: t('hwd.show_here', 'Show them here'),
  });
  show.addEventListener('click', () => closeHardwareDrawer());
  const note = el('p', { id: 'hwd-page-note', className: 'hwd-page-note' }, [
    el('span', { textContent: t('hwd.page_note', 'These settings are open in the Hardware panel.') }),
    ' ',
    show,
  ]);
  page.prepend(note);
}

/**
 * Opens the panel with a tab for each of `sections` (ids of TABS, in that order), on `tab` or the
 * first. Nothing opens when the list is empty.
 */
export async function openHardwareDrawer(sections, tab = null) {
  const tabs = Object.keys(TABS).filter((id) => (sections || []).includes(id));
  if (!tabs.length) return false;
  if (_open) closeHardwareDrawer();
  await ensureManagementDom();
  // the sections are filled as when the Hardware page opens (the fan and light controls, the status)
  await import('./management.js').then((m) => m.prepareHardwarePage()).catch(() => {});
  const drawer = shell();
  const tablist = drawer.querySelector('.hwd-tabs');
  const body = document.getElementById('hwd-panel');
  tablist.replaceChildren();
  body.replaceChildren();
  const moved = [];
  for (const id of tabs) {
    const btn = el('button', { type: 'button', id: `hwd-tab-${id}`, className: 'hwd-tab' });
    btn.textContent = t(...TABS[id].label);
    btn.dataset.tab = id;
    btn.setAttribute('role', 'tab');
    btn.setAttribute('aria-controls', 'hwd-panel');
    btn.addEventListener('click', () => showTab(id));
    tablist.append(btn);
    const group = el('div', { className: 'hwd-group' });
    group.dataset.tab = id;
    for (const paneId of TABS[id].panes) {
      const pane = document.getElementById(paneId);
      if (!pane) continue;
      const marker = document.createComment(`hw-drawer: ${paneId}`);
      pane.before(marker);
      moved.push({ pane, marker, display: pane.style.display });
      group.append(pane);
      pane.style.display = ''; // the page hides a section inline; in the panel its group decides
    }
    body.append(group);
  }
  _open = { tabs, active: tabs[0], moved, returnFocus: document.activeElement };
  showTab(tabs.includes(tab) ? tab : tabs[0]);
  pageNote();
  document.addEventListener('keydown', onKey, true);
  const backdrop = document.getElementById('hw-drawer-backdrop');
  drawer.hidden = false;
  backdrop.hidden = false;
  document.body.classList.add('hwd-is-open');
  requestAnimationFrame(() => {
    drawer.classList.add('open');
    backdrop.classList.add('open');
  });
  document.getElementById(`hwd-tab-${_open.active}`)?.focus();
  return true;
}

/** Closes the panel: every section goes back to its place on the Hardware page. */
export function closeHardwareDrawer() {
  if (!_open) return;
  const { moved, returnFocus } = _open;
  _open = null;
  document.removeEventListener('keydown', onKey, true);
  for (const { pane, marker, display } of moved) {
    marker.replaceWith(pane);
    pane.style.display = display;
  }
  document.getElementById('hwd-page-note')?.remove();
  const drawer = document.getElementById('hw-drawer');
  const backdrop = document.getElementById('hw-drawer-backdrop');
  drawer?.classList.remove('open');
  backdrop?.classList.remove('open');
  if (drawer) drawer.hidden = true;
  if (backdrop) backdrop.hidden = true;
  document.body.classList.remove('hwd-is-open');
  if (returnFocus && typeof returnFocus.focus === 'function' && document.contains(returnFocus)) returnFocus.focus();
}
