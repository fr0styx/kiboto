// Switch off when too hot (hardware extra, off by default): the Power page card.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { heatStatus, renderHeatShutdownCard } from '../components/heat-shutdown-card.js';
import { setLanguage } from '../i18n.js';

const ST = { enabled: false, hdd_c: 60, nvme_c: 80, hold_min: 3, can_power_off: true, engaged: false, last: null };

describe('switch off when too hot', () => {
  afterEach(async () => {
    vi.restoreAllMocks();
    await setLanguage('en');
    document.body.innerHTML = '';
  });

  it('says what it does', () => {
    expect(heatStatus(ST)).toBe('Off');
    expect(heatStatus(null)).toBe('Off');
    expect(heatStatus({ ...ST, enabled: true })).toBe('On: a hard drive at 60 °C or an NVMe drive at 80 °C for 3 minutes switches the NAS off.');
    expect(heatStatus({ ...ST, enabled: true, can_power_off: false })).toMatch(/stops the apps and virtual machines\.$/);
    expect(heatStatus({ ...ST, enabled: true, last: { at: 1795000000, outcome: 'off' } })).toMatch(/Last time \(.+\) it switched the NAS off\.$/);
    expect(heatStatus({ ...ST, enabled: true, last: { at: 1795000000, outcome: 'by_hand' } })).toMatch(/switched off by hand\.$/);
  });

  it('turns on and off from the card', async () => {
    document.body.innerHTML = '<section id="heat-shutdown-card" hidden></section>';
    let state = { ...ST };
    vi.spyOn(api, 'get').mockImplementation(async () => state);
    const put = vi.spyOn(api, 'put').mockImplementation(async (_url, body) => { state = { ...state, ...body }; return state; });
    await renderHeatShutdownCard();
    const card = document.getElementById('heat-shutdown-card');
    expect(card.hidden).toBe(false);
    expect(document.getElementById('heat-toggle').getAttribute('aria-pressed')).toBe('false');
    document.getElementById('heat-toggle').click();
    await vi.waitFor(() => expect(document.getElementById('heat-toggle').getAttribute('aria-pressed')).toBe('true'));
    expect(put).toHaveBeenCalledWith('/api/system/heat-shutdown', { enabled: true });
  });

  it('says why when saving fails, and hides when it cannot load', async () => {
    document.body.innerHTML = '<section id="heat-shutdown-card"></section>';
    vi.spyOn(api, 'get').mockResolvedValue({ ...ST, can_power_off: false });
    vi.spyOn(api, 'put').mockRejectedValue(new Error('No right'));
    await renderHeatShutdownCard();
    expect(document.querySelector('.fw-why').textContent).toMatch(/switch it off by hand/);
    document.getElementById('heat-toggle').click();
    await vi.waitFor(() => expect(document.getElementById('heat-error').hidden).toBe(false));
    expect(document.getElementById('heat-error').textContent).toBe('No right');
    vi.spyOn(api, 'get').mockRejectedValue(new Error('x'));
    expect(await renderHeatShutdownCard()).toBeNull();
    expect(document.getElementById('heat-shutdown-card').hidden).toBe(true);
    expect(await renderHeatShutdownCard(null)).toBeNull();
  });

  it('in German', async () => {
    await setLanguage('de');
    expect(heatStatus({ ...ST, enabled: true })).toMatch(/^An: /);
  });
});
