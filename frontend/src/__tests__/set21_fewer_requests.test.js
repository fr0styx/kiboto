import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api } from '../api.js';

const bk = await import('../components/management/backup.js');
const PAGE = `<div id="mgmt-pane-backups">
  <div id="snapshot-schedules-mount"></div><div id="offsite-backup-mount"></div>
  <details class="bk-all-versions"><summary>All</summary><div id="system-snapshots-mount"></div></details>
  <details class="bk-more"><summary>More</summary><div id="backup-jobs-mount"></div><div id="app-backups-mount"></div>
    <div id="two-way-sync-mount"></div><div id="protection-jobs-mount"></div></details></div>`;
const asked = (get) => get.mock.calls.map((c) => String(c[0]));

describe('Backup asks for less when it opens (SET-21, B13)', () => {
  let get;
  beforeEach(() => {
    vi.restoreAllMocks();
    get = vi.spyOn(api, 'get').mockResolvedValue({ jobs: [], snapshots: [], repos: [], schedules: [], backups: [] });
    document.body.innerHTML = PAGE;
  });

  it('the folded parts are not read until they are opened', async () => {
    bk.loadBackupPane(document);
    await new Promise((r) => setTimeout(r, 20));
    expect(asked(get)).not.toContain('/api/backup/snapshots');
    expect(asked(get)).not.toContain('/api/backup/schedule');
    const all = /** @type {HTMLDetailsElement} */ (document.querySelector('details.bk-all-versions'));
    all.open = true;
    all.dispatchEvent(new Event('toggle'));
    await vi.waitFor(() => expect(asked(get)).toContain('/api/backup/snapshots'));
    const more = /** @type {HTMLDetailsElement} */ (document.querySelector('details.bk-more'));
    more.open = true;
    more.dispatchEvent(new Event('toggle'));
    await vi.waitFor(() => expect(asked(get)).toContain('/api/backup/schedule'));
  });

  it('whenOpen runs at once without a fold, and binds a fold once', () => {
    const load = vi.fn();
    document.body.innerHTML = '<div id="x"></div><details id="d"><div id="y"></div></details>';
    expect(bk.whenOpen(document.getElementById('x'), load)).toBe(true);
    expect(bk.whenOpen(document.getElementById('y'), load)).toBe(false);
    expect(bk.whenOpen(document.getElementById('y'), load)).toBe(false);
    const d = /** @type {HTMLDetailsElement} */ (document.getElementById('d'));
    d.open = true;
    d.dispatchEvent(new Event('toggle'));
    expect(load).toHaveBeenCalledTimes(2);
  });
});
