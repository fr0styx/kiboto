import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { ROUTES } from '../router.js';
import { frontPanelParts, renderFrontPanel } from '../components/front-panel.js';

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
});
