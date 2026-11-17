// SET-31: with no UPS, "Set up a UPS" opens Advanced, where the connection settings are.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { fetchAndRenderUpsTelemetry } from '../components/management/ups.js';

afterEach(() => vi.restoreAllMocks());

describe('Set up a UPS', () => {
  it('opens the closed Advanced section', async () => {
    document.body.innerHTML = '<div id="mgmt-sec-ups"><div id="ups-status-line"></div><details id="pw-advanced"><summary>Advanced</summary><div id="ups-cockpit-config-section"></div></details></div>';
    vi.spyOn(api, 'get').mockResolvedValue({ available: false });
    await fetchAndRenderUpsTelemetry();
    const advanced = /** @type {HTMLDetailsElement} */ (document.getElementById('pw-advanced'));
    expect(advanced.open).toBe(false);
    /** @type {HTMLElement} */ (document.getElementById('ups-show-setup')).click();
    expect(advanced.open).toBe(true);
  });
});
