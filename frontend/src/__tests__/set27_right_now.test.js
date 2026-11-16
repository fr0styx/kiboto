import { describe, it, expect } from 'vitest';
import { ZettEventBus } from '../event-bus.js';
import { topApps, rightNowSentences, renderRightNow, installRightNow } from '../components/right-now.js';

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
    expect(rightNowSentences({ cpu: { util: 80 }, docker: DOCKER })[0]).toBe('The processor is busy: jellyfin is using most of it.');
    expect(rightNowSentences({ cpu: { util: 80 }, docker: [] })[0]).toBe('The processor is busy (80%).');
    expect(rightNowSentences({ cpu: { util: 5 }, mem: { pct: 95 } })).toContain('Memory is nearly full.');
    expect(rightNowSentences({ cpu: { util: 5 }, disks: [{ standby: true }, { standby: true }] })).toContain('The drives are asleep.');
    expect(rightNowSentences({ cpu: { util: 5 }, disks: [{ standby: false }, { standby: false }] })).toContain('All 2 drives are awake.');
    expect(rightNowSentences({ cpu: { util: 5 }, disks: [{ standby: false }, { standby: true }, { is_nvme: true }] })).toContain('1 drive awake, 1 asleep.');
  });

  it('draws the sentence and the apps, and keeps current while on screen', () => {
    document.body.innerHTML = '<section id="right-now" hidden></section>';
    const mount = /** @type {HTMLElement} */ (document.getElementById('right-now'));
    expect(renderRightNow(mount, { cpu: { util: 80 }, docker: DOCKER })).toBe(true);
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
});
