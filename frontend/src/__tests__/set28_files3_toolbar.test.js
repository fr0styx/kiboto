/** Files 3, design B (owner's pick, 16 Nov): View and More menus press the original buttons. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { installToolbarMenus, menuItems, openMenu } from '../components/fm-toolbar-menus.js';

function win() {
  document.body.innerHTML = `<div id="w"><div class="fm-toolbar">
    <button class="fm-locations-btn"></button><button class="fm-new-folder-btn"></button>
    <button class="fm-ai-search-toggle"></button><button class="fm-new-win-btn"></button><button class="fm-organize-btn" style="display:none"></button>
    <div class="fm-view-mode-group"><button class="fm-btn-view-list active"></button><button class="fm-btn-view-compact"></button><button class="fm-btn-view-icon"></button>
    <button class="fm-btn-hidden" aria-pressed="false"></button></div>
    <button class="fm-btn-transfers-toggle"><span class="fm-transfers-count-badge" style="display:inline">2</span></button>
    <button class="fm-btn-inspector-toggle"></button></div></div>`;
  return /** @type {HTMLElement} */ (document.getElementById('w'));
}

describe('Files 3 toolbar, design B', () => {
  afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = ''; });

  it('moves the view buttons and the rest out of sight and adds View and More after New folder', () => {
    const w = win();
    const r = installToolbarMenus(w);
    expect(r?.view.getAttribute('aria-label')).toBe('View');
    expect(r?.more.getAttribute('aria-label')).toBe('More');
    expect(w.querySelector('.fm-new-folder-btn')?.nextElementSibling).toBe(r?.view);
    expect(w.querySelectorAll('.fm-moved').length).toBe(10);
    expect(w.querySelector('.fm-view-mode-group')?.classList.contains('fm-moved')).toBe(true);
    expect(w.querySelector('.fm-new-folder-btn')?.classList.contains('fm-moved')).toBe(false);
    expect(installToolbarMenus(w)).toBeNull(); // once
    expect(installToolbarMenus(null)).toBeNull();
    expect(menuItems('view').length).toBe(4);
  });

  it('View shows the current choices and presses the original button', () => {
    const w = win();
    const { view } = /** @type {any} */ (installToolbarMenus(w));
    const icon = vi.fn();
    w.querySelector('.fm-btn-view-icon')?.addEventListener('click', icon);
    view.click();
    const items = [...w.querySelectorAll('.fm-menu-item')];
    expect(items.map((i) => i.textContent?.replace('✓', ''))).toEqual(['List', 'Compact list', 'Icons', 'Show hidden files']);
    expect(items[0].getAttribute('aria-checked')).toBe('true');
    expect(items[3].getAttribute('role')).toBe('menuitemcheckbox');
    expect(view.getAttribute('aria-expanded')).toBe('true');
    /** @type {HTMLButtonElement} */ (items[2]).click();
    expect(icon).toHaveBeenCalled();
    expect(w.querySelector('.fm-menu')).toBeNull();
  });

  it('More leaves out what is hidden, counts transfers, closes on Escape, outside click or a second press', () => {
    const w = win();
    const { more } = /** @type {any} */ (installToolbarMenus(w));
    more.click();
    const texts = [...w.querySelectorAll('.fm-menu-item')].map((i) => i.textContent);
    expect(texts).toEqual(['New window', 'Transfers (2)', 'Details', 'AI search']);
    const menu = /** @type {HTMLElement} */ (w.querySelector('.fm-menu'));
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(w.querySelector('.fm-menu')).toBeNull();
    more.click();
    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(w.querySelector('.fm-menu')).toBeNull();
    const bar = /** @type {HTMLElement} */ (w.querySelector('.fm-toolbar'));
    expect(openMenu(bar, more, 'more')).not.toBeNull();
    expect(openMenu(bar, more, 'more')).toBeNull(); // second press closes
  });
});
