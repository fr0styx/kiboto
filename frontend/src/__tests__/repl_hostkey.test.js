import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn() }));
const { api } = await import('../api.js');
const { showToast } = await import('../toast.js');

const setup = () => {
  document.body.innerHTML = `<section id='bk-replication'>
    <table><tbody id='replication-jobs-tbody'></tbody></table><table><tbody id='replication-history-tbody'></tbody></table></section>`;
};

const job = {
  id: 'j1',
  name: 'Off-site',
  source_pool: 'tank',
  source_dataset: 'family',
  target_type: 'remote_ssh',
  target_host: 'backup.lan',
  target_pool: 'backup',
  last_status: 'error',
  last_error: 'Kiboto does not recognise the other machine (server words)',
  last_error_key: 'host_key_changed',
};

describe('a copy whose other machine has a new identity (SSH host key)', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    setup();
    api.get.mockImplementation(async (url) =>
      url.endsWith('/jobs') ? { jobs: [job], available: true } : { history: [] }
    );
  });

  it('says why in words under the status, and offers to forget the old key', async () => {
    const { fetchAndRenderReplication } = await import('../components/management/network.js');
    await fetchAndRenderReplication();
    const row = document.getElementById('replication-jobs-tbody');
    expect(row.textContent).toContain('Kiboto does not recognise the other machine: its identity is not the one');
    expect(row.querySelector('.btn-forget-host')?.textContent).toBe('Forget its old key');
  });

  it('a failure of another kind is shown as the server said it, with no such button', async () => {
    const { replError } = await import('../components/management/network.js');
    expect(replError({ last_status: 'error', last_error: 'out of space <b>' })).toContain('out of space &lt;b&gt;');
    expect(replError({ last_status: 'success', last_error: 'old' })).toBe('');
    expect(replError({ last_status: 'error' })).toBe('');
  });

  it('forgetting asks first (confirmed), then shows the job again', async () => {
    const { fetchAndRenderReplication } = await import('../components/management/network.js');
    await fetchAndRenderReplication();
    api.post.mockResolvedValue({ forgotten: true });
    /** @type {HTMLButtonElement} */ (document.querySelector('.btn-forget-host')).click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalled());
    expect(api.post).toHaveBeenCalledWith('/api/storage/replication/jobs/j1/forget-host-key', {}, { confirmed: true });
    expect(showToast.mock.calls[0][1]).toBe('success');
    expect(api.get.mock.calls.filter(([url]) => url.endsWith('/jobs')).length).toBe(2);
  });

  it('a cancelled question says nothing; a refusal is said', async () => {
    const { forgetHostKey } = await import('../components/management/network.js');
    const btn = document.createElement('button');
    btn.dataset.id = 'j1';
    api.post.mockRejectedValueOnce(Object.assign(new Error('cancelled'), { error: 'cancelled' }));
    await forgetHostKey(btn);
    expect(showToast).not.toHaveBeenCalled();
    api.post.mockRejectedValueOnce(new Error('A copy on this machine signs in to no other machine.'));
    await forgetHostKey(btn);
    expect(showToast.mock.calls[0][1]).toBe('error');
    expect(btn.disabled).toBe(false);
  });
});
