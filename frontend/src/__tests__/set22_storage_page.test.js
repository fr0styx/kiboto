import { describe, it, expect, vi, afterEach } from 'vitest';
import markup from '../windows/management-window.html?raw';
import { api } from '../api.js';
import { ROUTES } from '../router.js';
import { tabForPane } from '../components/management.js';
import { storageItems, storageSentence, renderStorageSummary, watchedDrives } from '../components/storage-summary.js';

afterEach(() => vi.restoreAllMocks());

describe('Storage: one Drives tab with a summary, the bays and the pools (SET-22 Storage 3)', () => {
  it('the bays and the pools are one tab; a link to the pools opens it', () => {
    const doc = new DOMParser().parseFromString(markup, 'text/html');
    const card = /** @type {HTMLElement} */ (doc.getElementById('mgmt-sec-storage'));
    const tab = tabForPane(card, 'mgmt-pane-storage-topo');
    expect(tab?.dataset.tabTarget).toBe('mgmt-pane-chassis-twin');
    expect(tab?.textContent).toContain('Drives');
    expect(card.querySelector('[data-tab-target="mgmt-pane-storage-topo"]')).toBeNull();
    expect(card.querySelector('#mgmt-pane-chassis-twin #storage-summary')).not.toBeNull();
    expect(card.querySelector('[data-tab-target="mgmt-pane-storage-remotes"]')?.textContent).toContain('Cloud drives');
  });

  it('picks the drive, pool and space findings and says it in one sentence', () => {
    const summary = {
      items: [
        { id: 'drive:sdb', level: 'warning', kind: 'drive_warning', subject: 'sdb', open: 'drives' },
        { id: 'pool:main', level: 'critical', kind: 'pool_degraded', subject: 'main', open: 'storage' },
        { id: 'backup:x', level: 'warning', kind: 'backup_failed', open: 'backup' },
      ],
      unchecked: [],
    };
    expect(storageItems(summary).map((i) => i.id)).toEqual(['drive:sdb', 'pool:main']);
    expect(storageSentence(summary)).toEqual(['2 things on your drives need a look', 'bad']);
    expect(storageSentence({ items: [summary.items[0]] })).toEqual(['1 thing on your drives needs a look', 'warn']);
    expect(storageSentence({ items: [], unchecked: ['pools'] })[0]).toBe("Kiboto couldn't check every drive just now.");
    expect(storageSentence({ items: [], unchecked: ['power'] })).toEqual(['All drives are fine.', 'ok']);
  });

  it('draws the sentence, the findings with Open, and Check again', async () => {
    const mount = document.createElement('section');
    mount.hidden = true;
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      items: [{ id: 'drive:sdb', level: 'warning', kind: 'drive_warning', subject: 'sdb', open: 'storage' }],
      unchecked: [],
    });
    await renderStorageSummary(mount);
    expect(mount.hidden).toBe(false);
    expect(mount.textContent).toContain('1 thing on your drives needs a look');
    expect(mount.textContent).toContain('Drive sdb shows early warning signs.');
    const open = vi.spyOn(ROUTES, 'storage').mockImplementation(() => {});
    /** @type {HTMLElement} */ (mount.querySelector('[data-ov-open]')).click();
    expect(open).toHaveBeenCalled();
    get.mockResolvedValue({ items: [], unchecked: [] });
    /** @type {HTMLElement} */ (mount.querySelector('[data-sum-again]')).click();
    await vi.waitFor(() => expect(mount.textContent).toContain('All drives are fine.'));
    expect(mount.dataset.tone).toBe('ok');
  });

  it('a failed read says the drives were not all checked', async () => {
    const mount = document.createElement('section');
    vi.spyOn(api, 'get').mockRejectedValue(new Error('down'));
    await renderStorageSummary(mount);
    expect(mount.textContent).toContain("Kiboto couldn't check every drive just now.");
    expect(await renderStorageSummary(null)).toBeNull();
  });

  it('never says all drives are fine beside a drive marked "Keep an eye on it"', async () => {
    const chassis = {
      bays: [
        { slot_index: 1, disk: { model: 'ST22000DM000', verdict: 'watch' } },
        { slot_index: 4, disk: { model: 'ST22000DM000', verdict: 'ok' } },
        { slot_index: 0 },
      ],
      nvme_slots: [{ disk: { name: 'nvme0n1', verdict: 'watch' } }, {}],
    };
    expect(watchedDrives(chassis)).toEqual([
      { model: 'ST22000DM000', place: 'Bay 2' },
      { model: 'nvme0n1', place: 'M.2 slot 1' },
    ]);
    expect(watchedDrives(null)).toEqual([]);
    expect(storageSentence({ items: [] }, watchedDrives(chassis))).toEqual([
      'All drives work. Drive Health keeps an eye on 2 drives.',
      'ok',
    ]);
    expect(storageSentence({ items: [] }, [])[0]).toBe('All drives are fine.');
    document.body.innerHTML = '<div id="storage-summary" hidden></div>';
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url === '/api/chassis/config' ? { bays: [chassis.bays[0]] } : { items: [] }
    );
    await renderStorageSummary();
    const box = /** @type {HTMLElement} */ (document.getElementById('storage-summary'));
    expect(box.textContent).toContain('Drive Health keeps an eye on 1 drive.');
    expect(box.textContent).toContain('ST22000DM000 in Bay 2: keep an eye on it');
    expect(box.textContent).not.toContain('All drives are fine');
  });
});
