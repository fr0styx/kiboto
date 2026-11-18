import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
const { api } = await import('../api.js');

const setup = () => {
  document.body.innerHTML = `<section id='bk-replication' hidden>
    <table><tbody id='replication-jobs-tbody'></tbody></table><table><tbody id='replication-history-tbody'></tbody></table></section>`;
  return /** @type {HTMLElement} */ (document.getElementById('bk-replication'));
};

describe('B12b (REL-5): replication shows where it can run', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
  });

  it('shows it in Backup where this NAS can replicate', async () => {
    const box = setup();
    api.get.mockResolvedValue({ jobs: [], available: true, reason: '' });
    const { revealReplicationTab } = await import('../components/management/network.js');
    expect(await revealReplicationTab()).toBe(true);
    expect(box.hidden).toBe(false);
    expect(await revealReplicationTab()).toBe(true); // asked once
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('keeps it hidden elsewhere, and asks again after a failed check', async () => {
    const tab = setup();
    api.get
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({ jobs: [], available: false, reason: 'TrueNAS replicates its own pools' });
    const { revealReplicationTab } = await import('../components/management/network.js');
    expect(await revealReplicationTab()).toBe(false);
    expect(await revealReplicationTab()).toBe(false);
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(tab.hidden).toBe(true);
  });

  it('the list says why it cannot run, and shows each job as it is', async () => {
    setup();
    const { fetchAndRenderReplication } = await import('../components/management/network.js');
    api.get.mockImplementation(async (url) =>
      url.endsWith('/jobs')
        ? { jobs: [], available: false, reason: 'TrueNAS replicates its own pools' }
        : { history: [] }
    );
    await fetchAndRenderReplication();
    expect(document.getElementById('replication-jobs-tbody').textContent).toContain('TrueNAS replicates its own pools');
    const job = {
      id: 'j1',
      name: 'DR',
      source_pool: 'tank',
      source_dataset: 'family',
      target_type: 'local',
      target_pool: 'backup',
      schedule: 'daily',
      bandwidth_limit_kbps: 10240,
      retention_count: 7,
      last_status: 'error',
      last_error: 'out of space',
    };
    api.get.mockImplementation(async (url) =>
      url.endsWith('/jobs') ? { jobs: [job], available: true } : { history: [] }
    );
    await fetchAndRenderReplication();
    const row = document.getElementById('replication-jobs-tbody').textContent;
    expect(row).toContain('tank/family');
    expect(row).toContain('10 MB/s');
    expect(row).toContain('error');
  });

  it('the page has Replication in Backup -> More and no Storage tab for it (SET-22 Storage 3)', async () => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const html = readFileSync(resolve(__dirname, '../windows/management-window.html'), 'utf8');
    expect(html).not.toContain('data-tab-target="mgmt-pane-storage-replication"');
    expect(html).not.toContain('id="mgmt-pane-storage-replication"');
    const more = html.slice(
      html.indexOf('<details class="bk-more">'),
      html.indexOf('</details>', html.indexOf('<details class="bk-more">'))
    );
    expect(more).toContain('id="bk-replication"');
    expect(more).toContain('id="replication-jobs-tbody"');
    const mgmt = readFileSync(resolve(__dirname, '../components/management.js'), 'utf8');
    expect(mgmt).toContain(
      "'mgmt-pane-storage-replication': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-backups' }"
    );
  });
});
