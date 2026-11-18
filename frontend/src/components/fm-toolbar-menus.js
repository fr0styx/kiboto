/**
 * Files 3 (owner's pick, 16 Nov 2026: design B): a calmer File Explorer toolbar. Back, Forward, Up,
 * the path, Refresh, Search, Upload and New folder stay as icons with names in their tooltips; the
 * view buttons and the rest move into two icon menus, "View" and "More". The original buttons stay
 * in the page, out of sight, and the menus press them, so every existing handler keeps working.
 */
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';

const VIEW_SVG =
  '<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" aria-hidden="true"><line x1="4" y1="6" x2="20" y2="6"></line><line x1="4" y1="12" x2="20" y2="12"></line><line x1="4" y1="18" x2="20" y2="18"></line></svg>';
const MORE_SVG =
  '<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" aria-hidden="true"><circle cx="5" cy="12" r="1"></circle><circle cx="12" cy="12" r="1"></circle><circle cx="19" cy="12" r="1"></circle></svg>';

/** The selectors a menu proxies, in menu order, with their names and how their state is read. */
export function menuItems(kind) {
  if (kind === 'view') {
    return [
      { sel: '.fm-btn-view-list', role: 'menuitemradio', label: t('fm.v_list', 'List') },
      { sel: '.fm-btn-view-compact', role: 'menuitemradio', label: t('fm.v_compact', 'Compact list') },
      { sel: '.fm-btn-view-icon', role: 'menuitemradio', label: t('fm.v_icons', 'Icons') },
      { sel: '.fm-btn-hidden', role: 'menuitemcheckbox', label: t('fm.show_hidden', 'Show hidden files') },
    ];
  }
  return [
    { sel: '.fm-new-win-btn', role: 'menuitem', label: t('fm.m_new_window', 'New window') },
    { sel: '.fm-organize-btn', role: 'menuitem', label: t('fm.m_organize', 'Tidy films and series') },
    { sel: '.fm-btn-transfers-toggle', role: 'menuitem', label: t('fm.m_transfers', 'Transfers') },
    { sel: '.fm-btn-inspector-toggle', role: 'menuitem', label: t('fm.m_details', 'Details') },
    { sel: '.fm-ai-search-toggle', role: 'menuitemcheckbox', label: t('fm.m_ai', 'AI search') },
  ];
}

function shown(el) {
  return !!el && !el.hidden && el.style.display !== 'none' && !el.disabled;
}

function isOn(el) {
  return el.classList.contains('active') || el.getAttribute('aria-pressed') === 'true';
}

/** Puts View and More after New folder in the window's toolbar; returns the two buttons. */
export function installToolbarMenus(windowEl) {
  const bar = windowEl?.querySelector('.fm-toolbar');
  const anchor = bar?.querySelector('.fm-new-folder-btn');
  if (!bar || !anchor || bar.querySelector('.fm-menu-btn')) return null;
  for (const it of [...menuItems('view'), ...menuItems('more')]) bar.querySelector(it.sel)?.classList.add('fm-moved');
  // a group whose buttons all moved would leave its empty frame behind
  for (const g of bar.querySelectorAll('.fm-view-mode-group, .fm-aux-tool-group')) {
    if ([...g.children].every((c) => c.classList.contains('fm-moved'))) g.classList.add('fm-moved');
  }
  const make = (kind, svg, name) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = `fm-tool-btn fm-menu-btn fm-menu-${kind}`;
    b.title = name;
    b.setAttribute('aria-label', name);
    b.setAttribute('aria-haspopup', 'menu');
    b.setAttribute('aria-expanded', 'false');
    b.innerHTML = svg;
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      openMenu(bar, b, kind);
    });
    return b;
  };
  const view = make('view', VIEW_SVG, t('fm.m_view', 'View'));
  const more = make('more', MORE_SVG, t('fm.m_more', 'More'));
  anchor.after(view, more);
  return { view, more };
}

function closeMenus(bar) {
  bar.querySelectorAll('.fm-menu').forEach((m) => m.remove());
  bar.querySelectorAll('.fm-menu-btn').forEach((b) => b.setAttribute('aria-expanded', 'false'));
}

/** Opens a menu under its button; each item presses the original button. */
export function openMenu(bar, btn, kind) {
  const was = btn.getAttribute('aria-expanded') === 'true';
  closeMenus(bar);
  if (was) return null;
  const menu = document.createElement('div');
  menu.className = 'fm-menu';
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', btn.getAttribute('aria-label') || '');
  for (const it of menuItems(kind)) {
    const orig = /** @type {HTMLElement | null} */ (bar.querySelector(it.sel));
    if (!shown(orig)) continue;
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'fm-menu-item';
    item.setAttribute('role', it.role);
    let text = it.label;
    if (it.sel === '.fm-btn-transfers-toggle') {
      const n = /** @type {HTMLElement | null} */ (orig.querySelector('.fm-transfers-count-badge'));
      if (n && n.style.display !== 'none' && n.textContent !== '0') text = `${it.label} (${n.textContent})`;
    }
    if (it.role !== 'menuitem') item.setAttribute('aria-checked', isOn(orig) ? 'true' : 'false');
    item.innerHTML = `<span class="fm-menu-check" aria-hidden="true">${it.role !== 'menuitem' && isOn(orig) ? '✓' : ''}</span><span>${escapeHtml(text)}</span>`;
    item.addEventListener('click', (e) => {
      e.stopPropagation();
      closeMenus(bar);
      orig.click();
      btn.focus();
    });
    menu.append(item);
  }
  menu.addEventListener('keydown', (e) => {
    const items = /** @type {HTMLElement[]} */ ([...menu.querySelectorAll('.fm-menu-item')]);
    const i = items.indexOf(/** @type {HTMLElement} */ (document.activeElement));
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      closeMenus(bar);
      btn.focus();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      items[(i + 1) % items.length]?.focus();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      items[(i - 1 + items.length) % items.length]?.focus();
    }
  });
  btn.after(menu);
  btn.setAttribute('aria-expanded', 'true');
  menu.style.left = `${Math.max(0, btn.offsetLeft + btn.offsetWidth - 220)}px`;
  /** @type {HTMLElement | null} */ (menu.querySelector('.fm-menu-item'))?.focus();
  const away = (e) => {
    if (!menu.contains(/** @type {Node} */ (e.target))) {
      closeMenus(bar);
      document.removeEventListener('click', away, true);
    }
  };
  document.addEventListener('click', away, true);
  return menu;
}
