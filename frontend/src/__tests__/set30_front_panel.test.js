import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { ROUTES } from '../router.js';
import { frontPanelParts, renderFrontPanel, renderHardwarePower } from '../components/front-panel.js';

afterEach(() => vi.restoreAllMocks());

describe('General -> Front panel (SET-30, Hardware decision 2 a)', () => {
  it('knows which parts the machine has', () => {
    expect(frontPanelParts({ hardware: { has_mcu: true, has_lcd: true } })).toEqual({ light: true, screen: true });
    expect(frontPanelParts({ hardware: { is_zettlabs: true } })).toEqual({ light: true, screen: false });
    expect(frontPanelParts({})).toEqual({ light: false, screen: false });
  });

  it('stays hidden on a machine without them', async () => {
    const mount = document.createElement('section');
    expect(await renderFrontPanel(mount, { hardware: {} })).toBe(false);
    expect(mount.hidden).toBe(true);
    expect(await renderFrontPanel(null)).toBe(false);
  });

  it('turns the light and the screen off and on, and puts a switch back when that fails', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/led' ? { power: 'on' } : { power: false }));
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok' });
    const mount = document.createElement('section');
    expect(await renderFrontPanel(mount, { hardware: { has_mcu: true, has_lcd: true } })).toBe(true);
    const light = /** @type {HTMLInputElement} */ (mount.querySelector('#front-light-on'));
    const screen = /** @type {HTMLInputElement} */ (mount.querySelector('#front-screen-on'));
    expect(light.checked).toBe(true);
    expect(screen.checked).toBe(false);
    light.checked = false;
    light.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/led', { power: 'off' }));
    screen.checked = true;
    screen.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/screen', { power: true }));
    post.mockRejectedValueOnce(new Error('no right'));
    light.checked = true;
    light.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(light.disabled).toBe(false));
    expect(light.checked).toBe(false);
    const hw = vi.spyOn(ROUTES, 'hardware').mockImplementation(() => {});
    /** @type {HTMLElement} */ (mount.querySelector('.front-panel-more')).click();
    expect(hw).toHaveBeenCalled();
  });

  it('reads as on when the state cannot be read', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('x'));
    const mount = document.createElement('section');
    await renderFrontPanel(mount, { hardware: { has_mcu: true, has_lcd: true } });
    expect(/** @type {HTMLInputElement} */ (mount.querySelector('#front-light-on')).checked).toBe(true);
    expect(/** @type {HTMLInputElement} */ (mount.querySelector('#front-screen-on')).checked).toBe(true);
  });

  it('puts On/Off first in the Hardware page Lights and Front screen sections (Hardware 2)', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/led' ? { power: 'off' } : { power: true }));
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok' });
    document.body.innerHTML = '<div id="hw-light-power"></div><div id="hw-screen-power"></div>';
    await renderHardwarePower(document, { hardware: { has_mcu: true, has_lcd: true } });
    await renderHardwarePower(document, { hardware: { has_mcu: true, has_lcd: true } }); // once each
    const light = /** @type {HTMLInputElement} */ (document.querySelector('#hw-light-on'));
    expect(document.querySelectorAll('#hw-light-power input')).toHaveLength(1);
    expect(light.checked).toBe(false);
    expect(/** @type {HTMLInputElement} */ (document.querySelector('#hw-screen-on')).checked).toBe(true);
    light.checked = true;
    light.dispatchEvent(new Event('change'));
    await Promise.resolve();
    expect(post).toHaveBeenCalledWith('/api/led', { power: 'on' });
    document.body.innerHTML = '<div id="hw-light-power"></div><div id="hw-screen-power"></div>';
    await renderHardwarePower(document, { hardware: {} }); // a machine without them: nothing shown
    expect(document.querySelector('#hw-light-on')).toBe(null);
    document.body.innerHTML = '';
  });
});

describe('The On/Off rows say what they control', () => {
  it('name the part, say what the switch does, and show its state', async () => {
    const { lightRow } = await import('../components/front-panel.js');
    const { api } = await import('../api.js');
    vi.spyOn(api, 'get').mockResolvedValue({ power: 'off' });
    const post = vi.spyOn(api, 'post').mockResolvedValue({});
    const row = await lightRow('x-light');
    document.body.replaceChildren(row);
    const box = /** @type {HTMLInputElement} */ (row.querySelector('#x-light'));
    expect(row.querySelector('.front-panel-name').textContent).toBe('Front light');
    expect(row.querySelector('.front-panel-desc').textContent).toMatch(
      /light bar on the front of the server on or off/
    );
    expect(box.getAttribute('role')).toBe('switch');
    expect(box.getAttribute('aria-describedby')).toBe('x-light-desc');
    expect(row.querySelector('.front-panel-state').textContent).toBe('Off');
    expect(row.classList.contains('is-off')).toBe(true);
    box.click();
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/led', { power: 'on' }));
    expect(row.querySelector('.front-panel-state').textContent).toBe('On');
    expect(row.classList.contains('is-off')).toBe(false);
    vi.restoreAllMocks();
  });

  it('put the state back when the change is refused', async () => {
    const { screenRow } = await import('../components/front-panel.js');
    const { api } = await import('../api.js');
    vi.spyOn(api, 'get').mockResolvedValue({ power: true });
    vi.spyOn(api, 'post').mockRejectedValue(new Error('no'));
    const row = await screenRow('x-screen');
    document.body.replaceChildren(row);
    const box = /** @type {HTMLInputElement} */ (row.querySelector('#x-screen'));
    expect(row.querySelector('.front-panel-desc').textContent).toMatch(/small screen on the front/);
    box.click();
    await vi.waitFor(() => expect(box.disabled).toBe(false));
    expect(box.checked).toBe(true);
    expect(row.querySelector('.front-panel-state').textContent).toBe('On');
    vi.restoreAllMocks();
  });
});
