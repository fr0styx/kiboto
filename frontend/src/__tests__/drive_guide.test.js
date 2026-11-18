/** Audit A11: the drive replacement guide; steps per system, opened from the bay picture. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { guideSteps, openDriveGuide } from '../components/drive-guide.js';
import { api } from '../api.js';
import { renderChassisTwin } from '../components/chassis-visualizer.js';

const flush = () => new Promise((r) => setTimeout(r, 30));

const DRIVE = { model: 'ST22000DM000', serial: 'ZR51ABCD', size_formatted: '22.0 TB', dev: 'sdb' };

describe('drive replacement guide (audit A11)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('replace on Unraid: size rule, stop the array, swap, assign and rebuild', () => {
    const s = guideSteps('replace', 'unraid', DRIVE, 'Bay 2');
    expect(s[0]).toContain('important files have a copy');
    expect(s[1]).toBe('The drive: ST22000DM000 in Bay 2, serial ending ABCD. "Find this drive" lights its bay.');
    expect(s[2]).toContain('at least as large (22.0 TB)');
    expect(s.join(' ')).toContain("can't be larger than the parity drive");
    expect(s.join(' ')).toContain('stop the array');
    expect(s.join(' ')).toContain('Unraid rebuilds it from parity');
    expect(s.at(-1)).toContain('Which drive is in which bay');
  });

  it('replace on TrueNAS and elsewhere; add a drive on each system', () => {
    expect(guideSteps('replace', 'truenas', DRIVE, 'Bay 1').join(' ')).toContain('TrueNAS resilvers the pool');
    const other = guideSteps('replace', 'generic_linux', { model: 'X' }, 'Bay 3').join(' ');
    expect(other).toContain('Kiboto does not rebuild pools by itself yet');
    expect(other).toContain("Don't erase the old drive");
    expect(other).toContain('The drive: X in Bay 3.');
    expect(guideSteps('replace', '', {}, 'Bay 1').join(' ')).toContain('at least as large (?)');
    expect(guideSteps('add', 'unraid', {}, 'Bay 4').join(' ')).toContain('Unraid clears it first');
    expect(guideSteps('add', 'truenas', {}, 'Bay 4').join(' ')).toContain('Add VDEV');
    expect(guideSteps('add', 'other', {}, 'Bay 4').join(' ')).toContain('create a pool with the new drive');
  });

  it('the dialog names who does the work, lists the steps, and closes', () => {
    const dlg = openDriveGuide({ kind: 'replace', platform: 'unraid', drive: DRIVE, place: 'Bay 2' });
    expect(dlg.querySelector('h2')?.textContent).toBe('Replace this drive');
    expect(dlg.textContent).toContain(
      'Unraid does the work; these are the steps. Kiboto changes nothing on your pools.'
    );
    expect(dlg.querySelectorAll('li').length).toBeGreaterThan(5);
    const again = openDriveGuide({ kind: 'add', platform: 'other', place: 'Bay 6' });
    expect(document.querySelectorAll('#drive-guide-dialog').length).toBe(1);
    expect(again.textContent).toContain('These are the steps.');
    expect(again.querySelector('h2')?.textContent).toBe('Add a drive here');
    again.dispatchEvent(new Event('cancel'));
    expect(document.getElementById('drive-guide-dialog')).toBeNull();
    const third = openDriveGuide();
    /** @type {HTMLButtonElement} */ (third.querySelector('[data-dg-close]')).click();
    expect(document.getElementById('drive-guide-dialog')).toBeNull();
  });

  it('the bay picture offers Replace on a failing drive and Add on an empty bay', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ platform: 'unraid' });
    const box = document.createElement('div');
    document.body.append(box);
    renderChassisTwin(box, [], {
      chassisConfig: {
        total_bays: 3,
        bays: [
          {
            slot_index: 1,
            is_populated: true,
            disk: { ...DRIVE, health: 'PASSED', temp: 35, verdict: 'now', verdict_label_key: 'now_replace' },
          },
          {
            slot_index: 2,
            is_populated: true,
            disk: { ...DRIVE, dev: 'sdc', health: 'PASSED', temp: 34, verdict: 'watch', verdict_label_key: 'watch' },
          },
          { slot_index: 3, is_populated: false, disk: null },
        ],
      },
    });
    const replace = box.querySelectorAll('[data-guide="replace"]');
    expect(replace.length).toBe(1);
    /** @type {HTMLButtonElement} */ (replace[0]).click();
    await flush();
    expect(get).toHaveBeenCalledWith('/api/storage/platform');
    expect(document.getElementById('drive-guide-dialog')?.textContent).toContain('Unraid does the work');
    expect(document.getElementById('drive-guide-dialog')?.textContent).toContain('in Bay 1');
    get.mockRejectedValueOnce(new Error('offline'));
    /** @type {HTMLButtonElement} */ (box.querySelector('[data-guide="add"]')).click();
    await flush();
    expect(document.getElementById('drive-guide-dialog')?.querySelector('h2')?.textContent).toBe('Add a drive here');
    expect(document.getElementById('drive-guide-dialog')?.textContent).toContain('These are the steps.');
  });
});
