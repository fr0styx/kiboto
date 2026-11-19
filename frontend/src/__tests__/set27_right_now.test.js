import { describe, it, expect, vi, afterEach } from 'vitest';
import { ZettEventBus } from '../event-bus.js';
import { api } from '../api.js';
import {
  topApps,
  rightNowSentences,
  renderRightNow,
  installRightNow,
  runningJobs,
  refreshJobs,
} from '../components/right-now.js';

const DOCKER = [
  { name: 'jellyfin', state: 'running', cpu_pct: 61.2, mem_used: 512 * 1024 * 1024 },
  { name: 'kiboto', state: 'running', cpu_pct: 90, kiboto_own: true },
  { name: 'immich', state: 'running', cpu_pct: 3.1, mem_used: 900 * 1024 * 1024 },
  { name: 'old', state: 'exited', cpu_pct: 0 },
];

describe('Activity -> Right now (SET-27 Activity 3)', () => {
  it('lists the apps using the processor most, without Kiboto itself', () => {
    expect(topApps(DOCKER).map((c) => c.name)).toEqual(['jellyfin', 'immich']);
    expect(topApps(null)).toEqual([]);
  });

  it('says quiet, busy with which app, or just busy; memory and drives', () => {
    expect(rightNowSentences({ cpu: { util: 5 } })).toEqual(['Quiet.']);
    expect(rightNowSentences({ cpu: { util: 80 }, docker: DOCKER })[0]).toBe(
      'The processor is busy: jellyfin is using most of it.'
    );
    expect(rightNowSentences({ cpu: { util: 80 }, docker: [] })[0]).toBe('The processor is busy (80%).');
    expect(rightNowSentences({ cpu: { util: 5 }, mem: { pct: 95 } })).toContain('Memory is nearly full.');
    expect(rightNowSentences({ cpu: { util: 5 }, disks: [{ standby: true }, { standby: true }] })).toContain(
      'The drives are asleep.'
    );
    expect(rightNowSentences({ cpu: { util: 5 }, disks: [{ standby: false }, { standby: false }] })).toContain(
      'All 2 drives are awake.'
    );
    expect(
      rightNowSentences({ cpu: { util: 5 }, disks: [{ standby: false }, { standby: true }, { is_nvme: true }] })
    ).toContain('1 drive awake, 1 asleep.');
  });

  it('draws the sentence and the apps, and keeps current while on screen', () => {
    document.body.innerHTML = '<section id="right-now" hidden></section>';
    const mount = /** @type {HTMLElement} */ (document.getElementById('right-now'));
    expect(renderRightNow(mount, { cpu: { util: 80 }, docker: DOCKER }, [])).toBe(true); // no jobs: another test may have read some
    expect(mount.hidden).toBe(false);
    expect(mount.textContent).toContain('Apps by use');
    expect(mount.querySelectorAll('li').length).toBe(2);
    expect(mount.textContent).toContain('512 MB');
    expect(renderRightNow(null)).toBe(false);
    expect(installRightNow(mount)).toBe(true);
    Object.defineProperty(mount, 'offsetParent', { get: () => document.body });
    ZettEventBus.emit('stats:updated', { cpu: { util: 1 } });
    expect(mount.textContent).toContain('Quiet.');
    expect(installRightNow(null)).toBe(false);
  });

  describe('running jobs (SET-27 rest)', () => {
    afterEach(() => {
      vi.restoreAllMocks();
      delete globalThis.openJobsCentre;
    });
    const JOBS = {
      active: [
        { id: '1', title: 'Backup', status: 'running', percent: 40 },
        { id: '2', title: 'Drive test', title_id: 'jobs.kind_smart_test', status: 'queued' },
        { id: '3', title: 'Scrub', status: 'running', percent: 66.7 },
        { id: '4', title: 'Old', status: 'done', percent: 100 },
      ],
      history: [],
    };

    it('keeps the running, waiting and paused jobs, most advanced first', () => {
      expect(runningJobs(JOBS).map((j) => j.id)).toEqual(['3', '1', '2']);
      expect(runningJobs(null)).toEqual([]);
      expect(runningJobs({ active: 'x' })).toEqual([]);
    });

    it('lists them with progress and opens the Jobs list', () => {
      document.body.innerHTML = '<section id="right-now" hidden></section>';
      const mount = /** @type {HTMLElement} */ (document.getElementById('right-now'));
      const open = vi.fn();
      globalThis.openJobsCentre = open;
      renderRightNow(mount, { cpu: { util: 1 } }, runningJobs(JOBS));
      expect(mount.textContent).toContain('3 jobs running');
      expect(mount.textContent).toContain('Scrub');
      expect(mount.textContent).toContain('67%');
      expect(mount.textContent).toContain('Waiting');
      /** @type {HTMLButtonElement} */ (mount.querySelector('.right-now-open')).click();
      expect(open).toHaveBeenCalled();
      renderRightNow(mount, { cpu: { util: 1 } }, []);
      expect(mount.textContent).not.toContain('running');
    });

    it('asks the server at most every 15 seconds and keeps the list on a failure', async () => {
      const get = vi.spyOn(api, 'get').mockResolvedValue(JOBS);
      const t0 = Date.now() + 60_000; // later than any fetch an earlier test started
      const first = await refreshJobs(t0);
      expect(first.length).toBe(3);
      await refreshJobs(t0 + 5_000);
      expect(get).toHaveBeenCalledTimes(1);
      get.mockRejectedValueOnce(new Error('down'));
      expect((await refreshJobs(t0 + 20_000)).length).toBe(3);
      expect(get).toHaveBeenCalledTimes(2);
    });
  });
});
