import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// The top-bar Hardware button and its panel (owner, 25 Nov): one set of controls, the Hardware
// page's own sections moved into the panel; a tab only for hardware the machine has.
vi.mock('../management-dom.js', async (importOriginal) => ({
  ...(await importOriginal()),
  ensureManagementDom: () => Promise.resolve(),
}));

import { hardwareSections, mayChangeHardware, showHardwareButton } from '../components/dashboard.js';
import { openHardwareDrawer, closeHardwareDrawer, isOpen } from '../components/hardware-drawer.js';
import { showSystemFans } from '../components/management.js';

const ZETTLAB = {
  fans: [0, 0, 3100],
  fan_control: { driver_mode: 'mmio' },
  peripherals: { led_ready: true, led_port: '/dev/ttyACM0', fb_active: true },
  media_slots: { sd: { dev: 'sdb', size: 0 }, tf: { dev: 'sdc', size: 0 } },
};
const OWNER = { scopes: ['*'] };

function page() {
  document.body.innerHTML = `
    <button id="hw-drawer-btn" hidden>Hardware</button>
    <button id="elsewhere">elsewhere</button>
    <div id="mgmt-sec-hardware">
      <div id="mgmt-pane-unraid" class="mgmt-tab-pane" style="display: block;">
        <p id="hw-fans-system-note" hidden></p>
        <div class="profile-switcher-row"><button class="profile-btn">Quiet</button></div>
        <section id="quiet-night-card"></section>
      </div>
      <div id="mgmt-pane-hardware-fans" class="mgmt-tab-pane" style="display: block;"><div id="mgmt-pane-hardware-fans-slot"><input id="fan-x"></div></div>
      <div id="mgmt-pane-hardware-led" class="mgmt-tab-pane" style="display: block;"><button id="led-on">On</button></div>
      <div id="mgmt-pane-hardware-lcd" class="mgmt-tab-pane hw-absent" style="display: block;"></div>
      <div id="mgmt-pane-hardware-copy" class="mgmt-tab-pane" style="display: block;"></div>
      <div id="mgmt-pane-copy" class="mgmt-tab-pane" style="display: block;"></div>
    </div>`;
}

const order = () => [...document.querySelectorAll('#mgmt-sec-hardware > .mgmt-tab-pane')].map((n) => n.id);

describe('Which tabs and who sees the button', () => {
  afterEach(() => {
    delete globalThis.kibotoUser;
  });

  it('lists only the hardware the machine has', () => {
    expect(hardwareSections(ZETTLAB)).toEqual(['cooling', 'lights', 'screen', 'copies']);
    expect(hardwareSections({ fans: [1200], fan_control: { driver_mode: 'hwmon' } })).toEqual(['cooling']);
    // the D4: fans the kernel drives, readings only, still a Cooling tab
    expect(hardwareSections({ fans: [2500, 3000], fan_control: { driver_mode: 'none' } })).toEqual(['cooling']);
    expect(hardwareSections({ fans: [0], fan_control: { driver_mode: 'none' } })).toEqual([]);
    expect(hardwareSections({})).toEqual([]);
    expect(hardwareSections(null)).toEqual([]);
  });

  it('is for people who may change the fans or the light', () => {
    expect(mayChangeHardware(OWNER)).toBe(true);
    expect(mayChangeHardware({ scopes: ['hardware:fans'] })).toBe(true);
    expect(mayChangeHardware({ scopes: ['hardware:rgb'] })).toBe(true);
    expect(mayChangeHardware({ scopes: ['hardware:read', 'system:view'] })).toBe(false);
    expect(mayChangeHardware(undefined)).toBe(false);
  });

  it('shows the button only with some hardware and the right', () => {
    page();
    const btn = document.getElementById('hw-drawer-btn');
    globalThis.kibotoUser = OWNER;
    showHardwareButton(ZETTLAB);
    expect(btn.hidden).toBe(false);
    showHardwareButton({});
    expect(btn.hidden).toBe(true);
    globalThis.kibotoUser = { scopes: ['hardware:read'] };
    showHardwareButton(ZETTLAB);
    expect(btn.hidden).toBe(true);
  });
});

describe('The panel', () => {
  beforeEach(page);
  afterEach(() => closeHardwareDrawer());

  it('opens with a tab per section and moves the page sections into it', async () => {
    const before = order();
    document.getElementById('elsewhere').focus();
    expect(await openHardwareDrawer(['cooling', 'lights', 'copies'])).toBe(true);
    const tabs = [...document.querySelectorAll('.hwd-tab')].map((b) => b.textContent);
    expect(tabs).toEqual(['Cooling and fans', 'Lights', 'Card copies']);
    const drawer = document.getElementById('hw-drawer');
    expect(drawer.hidden).toBe(false);
    expect(drawer.getAttribute('role')).toBe('dialog');
    expect(drawer.contains(document.getElementById('mgmt-pane-unraid'))).toBe(true);
    expect(drawer.contains(document.getElementById('mgmt-pane-copy'))).toBe(true);
    expect(drawer.contains(document.getElementById('mgmt-pane-hardware-lcd'))).toBe(false); // no screen tab
    expect(document.getElementById('hwd-page-note')).not.toBeNull();
    expect(document.activeElement.id).toBe('hwd-tab-cooling');
    // only the active tab's sections show
    const groups = [...drawer.querySelectorAll('.hwd-group')];
    expect(groups.map((g) => g.hidden)).toEqual([false, true, true]);

    closeHardwareDrawer();
    expect(isOpen()).toBe(false);
    expect(order()).toEqual(before); // every section back in its place
    expect(document.getElementById('mgmt-pane-unraid').style.display).toBe('block');
    expect(document.getElementById('hwd-page-note')).toBeNull();
    expect(document.getElementById('hw-drawer').hidden).toBe(true);
    expect(document.activeElement.id).toBe('elsewhere');
  });

  it('opens on a named tab, and switches tabs by click and arrow keys', async () => {
    await openHardwareDrawer(['cooling', 'lights', 'copies'], 'lights');
    const sel = () => document.querySelector('.hwd-tab[aria-selected="true"]').dataset.tab;
    expect(sel()).toBe('lights');
    document.getElementById('hwd-tab-copies').click();
    expect(sel()).toBe('copies');
    const list = document.querySelector('.hwd-tabs');
    list.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(sel()).toBe('cooling');
    list.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    expect(sel()).toBe('copies');
    list.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
    expect(sel()).toBe('cooling');
    list.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
    expect(sel()).toBe('copies');
  });

  it('closes on Escape without letting it reach what is behind', async () => {
    const behind = vi.fn();
    document.addEventListener('keydown', behind);
    await openHardwareDrawer(['cooling']);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(isOpen()).toBe(false);
    expect(behind).not.toHaveBeenCalled();
    document.removeEventListener('keydown', behind);
  });

  it('closes from the close button, the backdrop and the page note', async () => {
    await openHardwareDrawer(['cooling']);
    document.querySelector('.hwd-close').click();
    expect(isOpen()).toBe(false);
    await openHardwareDrawer(['cooling']);
    document.getElementById('hw-drawer-backdrop').click();
    expect(isOpen()).toBe(false);
    await openHardwareDrawer(['cooling']);
    document.querySelector('#hwd-page-note button').click();
    expect(isOpen()).toBe(false);
  });

  it('opens nothing without hardware', async () => {
    expect(await openHardwareDrawer([])).toBe(false);
    expect(isOpen()).toBe(false);
  });
});

describe('Fans the system drives', () => {
  beforeEach(page);

  it('says so and rests the controls; Kiboto-driven fans keep them', () => {
    showSystemFans({ fans: [2500, 3000], fan_control: { driver_mode: 'none' } });
    expect(document.getElementById('hw-fans-system-note').hidden).toBe(false);
    expect(document.querySelector('.profile-switcher-row').inert).toBe(true);
    expect(document.getElementById('mgmt-pane-hardware-fans-slot').inert).toBe(true);
    showSystemFans({ fans: [0, 0, 3100], fan_control: { driver_mode: 'mmio' } });
    expect(document.getElementById('hw-fans-system-note').hidden).toBe(true);
    expect(document.querySelector('.profile-switcher-row').inert).toBe(false);
  });
});
