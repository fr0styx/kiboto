import { describe, it, expect, vi, beforeEach } from 'vitest';

const get = vi.fn();
const post = vi.fn();
vi.mock('../api.js', () => ({ api: { get, post, delete: vi.fn() } }));
const showToast = vi.fn();
vi.mock('../toast.js', () => ({ showToast, showConfirmToast: vi.fn() }));

const { fetchAndRenderBackupJobs } = await import('../components/management/backup.js');
const JOBS = [
  { id: 'a', name: 'Photos snapshots', enabled: false, destination_type: 'local_snapshot', schedule: 'daily' },
  { id: 'b', name: 'Old cloud copy', enabled: false, migrated_to: 'r1', destination_type: 'remote', schedule: 'daily' },
  { id: 'c', name: 'Active', enabled: true, destination_type: 'local_snapshot', schedule: 'daily', last_status: 'success' },
];

describe('paused backup jobs (SET-21 stage 3, Backup A11)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="m"></div>';
  });

  it('say Paused and switch back on; a moved job says where it went', async () => {
    get.mockResolvedValue({ jobs: JOBS });
    post.mockResolvedValue({});
    const mount = /** @type {HTMLElement} */ (document.getElementById('m'));
    await fetchAndRenderBackupJobs(mount);
    const rows = [...mount.querySelectorAll('tbody tr')].map((r) => r.textContent?.replace(/\s+/g, ' '));
    expect(rows[0]).toContain('Paused');
    expect(rows[1]).toContain('Moved to an off-site backup');
    expect(rows[2]).not.toContain('Paused');
    expect(mount.querySelectorAll('.btn-resume-backup-job').length).toBe(1);
    /** @type {HTMLElement} */ (mount.querySelector('.btn-resume-backup-job')).click();
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/backup/schedule', expect.objectContaining({ id: 'a', enabled: true, encryption_password: null })));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('"Photos snapshots" runs on its schedule again.', 'success'));
  });
});
