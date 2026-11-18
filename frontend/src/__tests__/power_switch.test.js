// SET-31, Power stage 4: Restart and Shut down, greyed with the reason where nothing can do it.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { renderPowerSwitch, switchSaid } from '../components/management/power-switch.js';

afterEach(() => vi.restoreAllMocks());
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('restart or shut down', () => {
  it('says what happened', () => {
    expect(switchSaid('reboot', true)).toMatch(/^The NAS is restarting/);
    expect(switchSaid('shutdown', true)).toMatch(/^The NAS is shutting down/);
    expect(switchSaid('reboot', false, 'exit 1')).toBe('Nothing was switched: exit 1');
  });

  it('greys a button with the reason, asks the server and draws once', async () => {
    document.body.innerHTML = '<section id="ps" hidden></section>';
    const mount = /** @type {HTMLElement} */ (document.getElementById('ps'));
    const get = vi
      .spyOn(api, 'get')
      .mockResolvedValue({ reboot: { ok: true }, shutdown: { ok: false, why: 'No host command is mounted.' } });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok' });
    await renderPowerSwitch(mount);
    expect(mount.hidden).toBe(false);
    const off = /** @type {HTMLButtonElement} */ (mount.querySelector('[data-power-action="shutdown"]'));
    expect(off.disabled).toBe(true);
    expect(mount.textContent).toContain('No host command is mounted.');
    /** @type {HTMLElement} */ (mount.querySelector('[data-power-action="reboot"]')).click();
    await flush();
    expect(post).toHaveBeenCalledWith('/api/system/reboot', {});
    await renderPowerSwitch(mount);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it('a cancelled confirmation changes nothing; a failure is said; no right, no section', async () => {
    document.body.innerHTML = '<section id="ps" hidden></section>';
    const mount = /** @type {HTMLElement} */ (document.getElementById('ps'));
    vi.spyOn(api, 'get').mockResolvedValue({ reboot: { ok: true }, shutdown: { ok: true } });
    const post = vi.spyOn(api, 'post').mockRejectedValue(Object.assign(new Error('Cancelled'), { error: 'cancelled' }));
    await renderPowerSwitch(mount);
    const btn = /** @type {HTMLButtonElement} */ (mount.querySelector('[data-power-action="shutdown"]'));
    btn.click();
    await flush();
    expect(btn.disabled).toBe(false);
    post.mockRejectedValue(new Error('exit 1'));
    btn.click();
    await flush();
    expect(btn.disabled).toBe(false);
    document.body.innerHTML = '<section id="ps2" hidden></section>';
    vi.spyOn(api, 'get').mockRejectedValue(new Error('forbidden'));
    const m2 = /** @type {HTMLElement} */ (document.getElementById('ps2'));
    await renderPowerSwitch(m2);
    expect(m2.hidden).toBe(true);
    await renderPowerSwitch(null);
  });
});
