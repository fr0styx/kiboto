// Quieter at night (hardware extra, off by default): the Hardware page card.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { quietStatus, renderQuietNightCard } from '../components/quiet-night-card.js';
import { setLanguage } from '../i18n.js';

const ST = { enabled: false, start: '23:00', end: '07:00', shift_c: 4, warm_c: 50, active_now: false };

describe('quieter at night', () => {
  afterEach(async () => {
    vi.restoreAllMocks();
    await setLanguage('en');
    document.body.innerHTML = '';
  });

  it('says what it does', () => {
    expect(quietStatus(ST)).toBe('Off');
    expect(quietStatus(null)).toBe('Off');
    expect(quietStatus({ ...ST, enabled: true })).toBe('On from 23:00 to 07:00.');
    expect(quietStatus({ ...ST, enabled: true, active_now: true })).toBe('On from 23:00 to 07:00. Quieter now.');
  });

  it('turns on with the times, and saves new times', async () => {
    document.body.innerHTML = '<section id="quiet-night-card" hidden></section>';
    let state = { ...ST };
    vi.spyOn(api, 'get').mockImplementation(async () => state);
    const put = vi.spyOn(api, 'put').mockImplementation(async (_u, body) => { state = { ...state, ...body }; return state; });
    await renderQuietNightCard();
    expect(document.querySelector('.fw-why').textContent).toMatch(/4 °C cooler\. From 50 °C/);
    document.getElementById('qn-toggle').click();
    await vi.waitFor(() => expect(document.getElementById('qn-toggle').getAttribute('aria-pressed')).toBe('true'));
    expect(put).toHaveBeenLastCalledWith('/api/fans/quiet-night', { enabled: true, start: '23:00', end: '07:00' });
    document.getElementById('qn-start').value = '22:00';
    document.getElementById('qn-save').click();
    await vi.waitFor(() => expect(put).toHaveBeenLastCalledWith('/api/fans/quiet-night', { enabled: true, start: '22:00', end: '07:00' }));
  });

  it('says why when saving fails, and hides when it cannot load', async () => {
    document.body.innerHTML = '<section id="quiet-night-card"></section>';
    vi.spyOn(api, 'get').mockResolvedValue(ST);
    vi.spyOn(api, 'put').mockRejectedValue(new Error('Use times like 23:00 and 07:00.'));
    await renderQuietNightCard();
    document.getElementById('qn-save').click();
    await vi.waitFor(() => expect(document.getElementById('qn-error').hidden).toBe(false));
    vi.spyOn(api, 'get').mockRejectedValue(new Error('x'));
    expect(await renderQuietNightCard()).toBeNull();
    expect(document.getElementById('quiet-night-card').hidden).toBe(true);
    expect(await renderQuietNightCard(null)).toBeNull();
  });

  it('in German', async () => {
    await setLanguage('de');
    expect(quietStatus({ ...ST, enabled: true })).toMatch(/23:00/);
    expect(quietStatus({ ...ST, enabled: true })).not.toBe('On from 23:00 to 07:00.');
  });
});
