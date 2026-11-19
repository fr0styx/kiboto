// Drive Health: "Check this new drive" (owner's decision, 19 Nov 2026).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '../api.js';
import { showToast } from '../toast.js';
import {
  mountDriveCheck,
  resetDriveCheckForTesting,
  verdictSaid,
  factsSaid,
  progressSaid,
} from '../components/drive-check.js';

vi.mock('../toast.js', async (orig) => ({ ...(await orig()), showToast: vi.fn() }));

const GIB = 1024 ** 3;
const FREE = { dev: 'sdc', size_bytes: 4000 * GIB, free: true, in_use: null, check: null, last: null };
const GOING = {
  dev: 'sdc',
  state: 'running',
  size_bytes: 4000 * GIB,
  read_bytes: 1000 * GIB,
  speed_bps: 180e6,
  eta_secs: 5 * 3600,
};
const DONE = {
  dev: 'sdc',
  state: 'finished',
  verdict: 'good',
  size_bytes: 4000 * GIB,
  read_bytes: 4000 * GIB,
  started: 1795000000,
  ended: 1795030000,
  slowest_bps: 95e6,
  unreadable: 0,
};
const view = (drive) => ({
  drives: [{ dev: 'sda', free: false, in_use: 'pool', check: null, last: null }, drive],
  max_at_once: 2,
});
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('check this new drive', () => {
  let box;
  beforeEach(() => {
    resetDriveCheckForTesting();
    document.body.innerHTML = '<section id="dh-newcheck" hidden></section>';
    box = document.getElementById('dh-newcheck');
  });
  afterEach(() => {
    resetDriveCheckForTesting();
    vi.restoreAllMocks();
    vi.mocked(showToast).mockClear();
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('says what a check found in words a person can act on', () => {
    expect(verdictSaid(DONE)).toMatch(/^This drive is good to use/);
    expect(verdictSaid({ ...DONE, verdict: 'bad' })).toMatch(/^Do not trust this drive with data/);
    expect(verdictSaid({ ...DONE, verdict: 'cable' })).toMatch(/usually the cable or the bay/);
    expect(verdictSaid({ state: 'stopped' })).toMatch(/^Stopped before the end/);
    expect(verdictSaid({ state: 'too_hot', why: '57' })).toMatch(/the drive reached 57 °C/);
    expect(verdictSaid({ state: 'failed', why: 'No such device' })).toMatch(/stopped answering \(No such device\)/);
    expect(factsSaid(DONE)).toMatch(/^Read .* of .* · took 8h 20m · slowest stretch .*\/s · nothing unreadable$/);
    expect(factsSaid({ ...DONE, unreadable: 1 })).toMatch(/1 place could not be read$/);
    expect(factsSaid({ ...DONE, unreadable: 3, slowest_bps: null, ended: null })).toMatch(
      /of [^·]+ · 3 places could not be read$/
    );
    expect(factsSaid({})).toMatch(/nothing unreadable$/);
    expect(progressSaid(GOING)).toMatch(/^25 % read · .*\/s · about 5h 0m left$/);
    expect(progressSaid({ size_bytes: 0 })).toBe('0 % read');
  });

  it('is not shown for a drive that is in use and was never checked, or when the list cannot be read', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view(FREE));
    expect(await mountDriveCheck(box, 'sda')).toBe(false);
    expect(box.hidden).toBe(true);
    expect(await mountDriveCheck(box, 'sdz')).toBe(false);
    vi.mocked(api.get).mockRejectedValue(new Error('offline'));
    expect(await mountDriveCheck(box, 'sdc')).toBe(false);
    expect(await mountDriveCheck(null, 'sdc')).toBe(false);
    expect(await mountDriveCheck(box, '')).toBe(false);
  });

  it('offers the check for a free drive and starts it', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue(view(FREE));
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'started' });
    expect(await mountDriveCheck(box, 'sdc')).toBe(true);
    expect(box.hidden).toBe(false);
    expect(box.textContent).toContain('Check this new drive');
    expect(box.textContent).toContain('Nothing is written to it');
    const start = box.querySelector('[data-dc-act="start"]');
    expect(start.textContent).toBe('Check this drive');
    get.mockResolvedValue(view({ ...FREE, check: GOING }));
    start.click();
    await flush();
    await flush();
    expect(post).toHaveBeenCalledWith('/api/drives/sdc/check', {});
    expect(showToast).toHaveBeenCalledWith('The check has started. You can close this window; it goes on.', 'success');
    expect(box.querySelector('[data-dc-act="start"]')).toBe(null);
    expect(box.querySelector('progress').value).toBe(25);
    expect(box.querySelector('#dc-progress').textContent).toMatch(/^25 % read/);
    get.mockResolvedValue(view({ ...FREE, last: { ...DONE, state: 'stopped', verdict: 'unfinished' } }));
    box.querySelector('[data-dc-act="stop"]').click();
    await flush();
    await flush();
    expect(post).toHaveBeenLastCalledWith('/api/drives/sdc/check/stop', {});
    expect(box.textContent).toContain('Stopped before the end');
    expect(box.querySelector('[data-dc-act="start"]')).not.toBe(null);
  });

  it('says why a start was refused, and says nothing when the person cancelled', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view(FREE));
    const post = vi.spyOn(api, 'post').mockRejectedValue(new Error('Two drives are being checked already.'));
    await mountDriveCheck(box, 'sdc');
    box.querySelector('[data-dc-act="start"]').click();
    await flush();
    await flush();
    expect(showToast).toHaveBeenCalledWith("That didn't work: Two drives are being checked already.", 'error');
    vi.mocked(showToast).mockClear();
    post.mockRejectedValue(Object.assign(new Error('cancelled'), { error: 'cancelled' }));
    box.querySelector('[data-dc-act="start"]').click();
    await flush();
    await flush();
    expect(showToast).not.toHaveBeenCalled();
  });

  it('shows the last result, also for a drive that has since gone into a pool', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view({ ...FREE, free: false, in_use: 'pool', last: DONE }));
    expect(await mountDriveCheck(box, 'sdc')).toBe(true);
    expect(box.querySelector('.dc-verdict.is-good').textContent).toMatch(/good to use/);
    expect(box.textContent).toContain('Last check ');
    expect(box.querySelector('[data-dc-act]')).toBe(null); // in use now: no button
    vi.mocked(api.get).mockResolvedValue(
      view({ ...FREE, last: { ...DONE, state: 'too_hot', why: '56', verdict: 'unfinished' } })
    );
    await mountDriveCheck(box, 'sdc');
    expect(box.querySelector('.dc-verdict.is-unfinished').textContent).toMatch(/reached 56 °C/);
  });

  it('looks again while a check is going, shows the result when it ends, and stops when the page is gone', async () => {
    vi.useFakeTimers();
    const get = vi.spyOn(api, 'get').mockResolvedValue(view({ ...FREE, check: GOING }));
    await mountDriveCheck(box, 'sdc');
    expect(get).toHaveBeenCalledTimes(1);
    get.mockResolvedValue(view({ ...FREE, check: { ...GOING, read_bytes: 2000 * GIB } }));
    await vi.advanceTimersByTimeAsync(5100);
    expect(box.querySelector('progress').value).toBe(50);
    get.mockRejectedValueOnce(new Error('blip'));
    await vi.advanceTimersByTimeAsync(5100); // one failed look changes nothing
    expect(box.querySelector('progress').value).toBe(50);
    get.mockResolvedValue(view({ ...FREE, last: DONE }));
    await vi.advanceTimersByTimeAsync(5100);
    expect(box.textContent).toContain('good to use');
    const calls = get.mock.calls.length;
    await vi.advanceTimersByTimeAsync(20000);
    expect(get.mock.calls.length).toBe(calls); // it ended: nothing more is asked
    get.mockResolvedValue(view({ ...FREE, check: GOING }));
    await mountDriveCheck(box, 'sdc');
    const before = get.mock.calls.length;
    box.remove();
    await vi.advanceTimersByTimeAsync(12000);
    expect(get.mock.calls.length).toBe(before);
  });
});
