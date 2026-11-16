/** Audit A10: Switch off at night on the Power page. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { renderPowerScheduleCard, scheduleStatus } from '../components/power-schedule-card.js';

const flush = () => new Promise((r) => setTimeout(r, 10));
const OFF = { enabled: false, off_at: '01:00', wake_at: '07:00', days: [0, 1, 2, 3, 4, 5, 6], last_note: '', wake_possible: true };

describe('switch off at night (audit A10)', () => {
  afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = ''; });

  it('says off, the times, and what happened last time', () => {
    expect(scheduleStatus(null)).toBe('Off');
    expect(scheduleStatus(OFF)).toBe('Off');
    const on = { ...OFF, enabled: true };
    expect(scheduleStatus(on)).toBe('Switches off at 01:00 and wakes at 07:00.');
    expect(scheduleStatus({ ...on, last_note: 'no_wake' })).toContain('the wake-up clock could not be set');
    expect(scheduleStatus({ ...on, last_note: 'failed' })).toContain('did not work');
    expect(scheduleStatus({ ...on, last_note: 'postponed:job' })).toContain('something is still running');
  });

  it('turns on with the chosen times and nights, and shows a refusal', async () => {
    document.body.innerHTML = '<section id="power-schedule-card" hidden></section>';
    let st = { ...OFF };
    vi.spyOn(api, 'get').mockImplementation(async () => st);
    const put = vi.spyOn(api, 'put').mockImplementation(async (_u, body) => { st = { ...st, ...body }; return st; });
    await renderPowerScheduleCard();
    const box = /** @type {HTMLElement} */ (document.getElementById('power-schedule-card'));
    expect(box.textContent).toContain('never switches off without one');
    /** @type {HTMLInputElement} */ (box.querySelector('#ps-off')).value = '23:30';
    /** @type {HTMLInputElement} */ (box.querySelector('[data-ps-day="2"]')).checked = false;
    /** @type {HTMLButtonElement} */ (box.querySelector('#ps-toggle')).click();
    await flush();
    expect(put).toHaveBeenLastCalledWith('/api/system/power-schedule', { enabled: true, off_at: '23:30', wake_at: '07:00', days: [0, 1, 3, 4, 5, 6] });
    expect(box.querySelector('#ps-status')?.textContent).toBe('Switches off at 23:30 and wakes at 07:00.');
    put.mockRejectedValueOnce(new Error('Choose at least one night.'));
    /** @type {HTMLButtonElement} */ (box.querySelector('#ps-save')).click();
    await flush();
    expect(box.querySelector('#ps-error')?.textContent).toBe('Choose at least one night.');
  });

  it('without a settable wake-up clock the switch is locked and it says why; hidden when not allowed', async () => {
    document.body.innerHTML = '<section id="power-schedule-card" hidden></section>';
    vi.spyOn(api, 'get').mockResolvedValueOnce({ ...OFF, wake_possible: false });
    await renderPowerScheduleCard();
    const box = /** @type {HTMLElement} */ (document.getElementById('power-schedule-card'));
    expect(/** @type {HTMLButtonElement} */ (box.querySelector('#ps-toggle')).disabled).toBe(true);
    expect(box.textContent).toContain("wake-up clock can't be set");
    vi.mocked(api.get).mockRejectedValueOnce(new Error('403'));
    expect(await renderPowerScheduleCard(box)).toBeNull();
    expect(box.hidden).toBe(true);
    expect(await renderPowerScheduleCard(null)).toBeNull();
  });
});
