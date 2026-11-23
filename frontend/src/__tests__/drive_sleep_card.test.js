// Let hard drives sleep (off by default): the Power page card, shown only on a managed host.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { renderDriveSleepCard, sleepLabel, sleepStatus } from '../components/drive-sleep-card.js';
import { setLanguage } from '../i18n.js';

const ST = { minutes: 0, last: [], choices: [0, 10, 15, 20, 30, 60, 120, 180], applies: true };

describe('let hard drives sleep', () => {
  afterEach(async () => {
    vi.restoreAllMocks();
    await setLanguage('en');
    document.body.innerHTML = '';
  });

  it('names the times', () => {
    expect(sleepLabel(0)).toBe('Off');
    expect(sleepLabel(20)).toBe('After 20 minutes');
    expect(sleepLabel(60)).toBe('After 1 hour');
    expect(sleepLabel(120)).toBe('After 2 hours');
  });

  it('says what it does and which drives did not take it', () => {
    expect(sleepStatus(null)).toBe('Off: the drives keep spinning.');
    expect(sleepStatus({ ...ST, minutes: 30, last: [{ drive: 'sdb', state: 'set' }] })).toBe(
      'Spinning drives sleep after 30 minutes with nothing to do.'
    );
    const s = sleepStatus({
      ...ST,
      minutes: 60,
      last: [
        { drive: 'sdb', state: 'failed' },
        { drive: 'sdc', state: 'asleep' },
      ],
    });
    expect(s).toMatch(/refused the timer: sdb\./);
    expect(s).toMatch(/until the next start: sdc\.$/);
    expect(sleepStatus({ ...ST, minutes: 10, last: [] })).toMatch(/No spinning data drives were found\.$/);
  });

  it('saves a new time from the list', async () => {
    document.body.innerHTML = '<section id="drive-sleep-card" hidden></section>';
    let state = { ...ST };
    vi.spyOn(api, 'get').mockImplementation(async () => state);
    const put = vi.spyOn(api, 'put').mockImplementation(async (_url, body) => {
      state = { ...state, ...body, last: [{ drive: 'sdb', state: 'set' }] };
      return state;
    });
    await renderDriveSleepCard();
    expect(document.getElementById('drive-sleep-card').hidden).toBe(false);
    const pick = /** @type {HTMLSelectElement} */ (document.getElementById('ds-minutes'));
    pick.value = '20';
    pick.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(put).toHaveBeenCalledWith('/api/system/drive-sleep', { minutes: 20 }));
    await vi.waitFor(() => expect(document.getElementById('ds-status').textContent).toMatch(/20 minutes/));
  });

  it('stays hidden where the host decides, says why a save failed, and hides when it cannot load', async () => {
    document.body.innerHTML = '<section id="drive-sleep-card"></section>';
    vi.spyOn(api, 'get').mockResolvedValueOnce({ ...ST, applies: false });
    await renderDriveSleepCard();
    expect(document.getElementById('drive-sleep-card').hidden).toBe(true);
    vi.spyOn(api, 'get').mockResolvedValue({ ...ST });
    vi.spyOn(api, 'put').mockRejectedValue(new Error('No right'));
    await renderDriveSleepCard();
    const pick = /** @type {HTMLSelectElement} */ (document.getElementById('ds-minutes'));
    pick.value = '10';
    pick.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(document.getElementById('ds-error').hidden).toBe(false));
    expect(document.getElementById('ds-error').textContent).toBe('No right');
    vi.spyOn(api, 'get').mockRejectedValue(new Error('x'));
    expect(await renderDriveSleepCard()).toBeNull();
    expect(await renderDriveSleepCard(null)).toBeNull();
  });
});
