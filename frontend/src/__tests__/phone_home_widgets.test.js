import { describe, it, expect, afterEach } from 'vitest';
import { enablePhoneShell, tabForPage } from '../components/phone-shell.js';

const tick = () => new Promise((r) => setTimeout(r, 30));

afterEach(() => enablePhoneShell(false));

describe('phone Home is a home screen with widgets; Settings has the tiles', () => {
  it('the desktop widgets live on Home while the phone shell is on, and go back after', () => {
    document.body.innerHTML =
      '<main id="desk"><div id="desktop-widgets-container"><div class="desktop-widget" id="widget-clock"></div></div><i id="after"></i></main>';
    enablePhoneShell(true);
    const w = document.getElementById('desktop-widgets-container');
    expect(w?.parentElement?.id).toBe('phone-widgets');
    expect(document.getElementById('phone-launcher')?.dataset.view).toBe('home');
    enablePhoneShell(false);
    expect(document.getElementById('desktop-widgets-container')?.parentElement?.id).toBe('desk');
    expect(document.getElementById('desktop-widgets-container')?.nextElementSibling?.id).toBe('after');
  });

  it('widgets drawn after the shell still come to Home', async () => {
    document.body.innerHTML = '';
    enablePhoneShell(true);
    const w = document.createElement('div');
    w.id = 'desktop-widgets-container';
    document.body.append(w);
    document.body.classList.add('x'); // any change wakes the observer
    await tick();
    expect(w.parentElement?.id).toBe('phone-widgets');
  });

  it('the Settings tab shows every section as a tile, Home shows the widgets again', async () => {
    document.body.innerHTML = '';
    enablePhoneShell(true);
    const launcher = /** @type {HTMLElement} */ (document.getElementById('phone-launcher'));
    /** @type {HTMLElement} */ (document.querySelector('[data-phone-tab="settings"]')).click();
    await tick();
    expect(launcher.dataset.view).toBe('settings');
    expect(tabForPage(null)).toBe('settings');
    expect(document.querySelector('[data-phone-tab="settings"]')?.classList.contains('is-current')).toBe(true);
    expect(launcher.querySelector('.phone-settings [data-phone-open="storage"]')).not.toBeNull();
    expect(launcher.querySelector('[data-phone-open="settings"] span')?.textContent).toBe('General');
    /** @type {HTMLElement} */ (document.querySelector('[data-phone-tab="home"]')).click();
    await tick();
    expect(launcher.dataset.view).toBe('home');
    expect(document.querySelector('[data-phone-tab="home"]')?.classList.contains('is-current')).toBe(true);
  });

  it('a page opened from the Settings tiles belongs to the Settings tab', async () => {
    document.body.innerHTML = '';
    window.openManagementSection = () => {};
    enablePhoneShell(true);
    /** @type {HTMLElement} */ (document.querySelector('[data-phone-tab="settings"]')).click();
    /** @type {HTMLElement} */ (document.querySelector('[data-phone-open="storage"]')).click();
    const mw = document.createElement('div');
    mw.id = 'management-window';
    expect(tabForPage(mw)).toBe('settings');
  });
});
