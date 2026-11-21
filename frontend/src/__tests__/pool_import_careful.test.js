/** Importing a pool from elsewhere: read-only first, and force only after the warning. */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showDangerConfirm: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));
const { api } = await import('../api.js');
const { showToast, showDangerConfirm, showConfirmToast } = await import('../toast.js');
const { importFoundPool, foundPoolsHtml, renderStructuredPoolsTopology } =
  await import('../components/chassis-visualizer.js');

function button() {
  document.body.innerHTML = foundPoolsHtml([{ pool_id: 'tank', fs_type: 'zfs', status: 'ONLINE', numeric_id: '4711' }]);
  return /** @type {HTMLButtonElement} */ (document.querySelector('.btn-import-external-pool'));
}

describe('importing a found pool', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(api, 'get').mockResolvedValue({});
  });

  it('sends the id the look showed and says the pool is only being read', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'imported', read_only: true });
    const btn = button();
    expect(btn.dataset.guid).toBe('4711');
    await importFoundPool(document.body, btn);
    expect(post).toHaveBeenCalledWith('/api/storage/pools/import', { pool_id: 'tank', fs_type: 'zfs', guid: '4711' });
    expect(showToast.mock.calls.at(-1)[0]).toContain('Nothing on it was changed');
  });

  it('asks before forcing a pool another system had, and forces only on a yes', async () => {
    const refusal = Object.assign(new Error('tank was last used by another system.'), { error: 'pool_used_elsewhere' });
    const post = vi.spyOn(api, 'post').mockRejectedValueOnce(refusal).mockResolvedValue({ read_only: true });
    const btn = button();
    await importFoundPool(document.body, btn);
    expect(post).toHaveBeenCalledTimes(1);
    expect(btn.disabled).toBe(false);
    const [title, msg, onOk, , opts] = showDangerConfirm.mock.calls.at(-1);
    expect(title).toBe('This pool was last used by another system');
    expect(msg).toContain('Two systems using one pool at the same time destroy it');
    expect(opts.okText).toBe('Import anyway');
    await onOk();
    expect(post).toHaveBeenLastCalledWith('/api/storage/pools/import', {
      pool_id: 'tank',
      fs_type: 'zfs',
      guid: '4711',
      force: true,
    });
  });

  it('says any other failure as it is and frees the button', async () => {
    vi.spyOn(api, 'post').mockRejectedValue(new Error('one or more devices is currently unavailable'));
    const btn = button();
    await importFoundPool(document.body, btn);
    expect(showDangerConfirm).not.toHaveBeenCalled();
    expect(showToast.mock.calls.at(-1)).toEqual(['one or more devices is currently unavailable', 'error']);
    expect(btn.disabled).toBe(false);
  });
});

describe('a pool that is only being read', () => {
  const POOLS = {
    is_observer_mode: false,
    platform: 'generic_linux',
    pools: [
      { id: 'tank', name: 'tank', fs_type: 'zfs', disks: [], status: 'HEALTHY', read_only: true },
      { id: 'vault', name: 'vault', fs_type: 'zfs', disks: [], status: 'HEALTHY' },
    ],
  };
  let box;
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="topo"></div>';
    box = document.getElementById('topo');
    vi.spyOn(api, 'get').mockResolvedValue(POOLS);
    renderStructuredPoolsTopology(box, POOLS);
  });

  it('says so on its card and offers to allow changes, on that pool only', () => {
    const buttons = [...box.querySelectorAll('.btn-pool-writable')];
    expect(buttons.map((b) => b.dataset.poolId)).toEqual(['tank']);
    expect(buttons[0].textContent).toBe('Allow changes');
    expect(box.textContent).toContain('Read-only');
  });

  it('asks, then allows changes, and says why when it could not', async () => {
    box.querySelector('.btn-pool-writable').click();
    const [title, msg, onOk, , opts] = showConfirmToast.mock.calls.at(-1);
    expect(title).toBe('Allow changes to this pool');
    expect(msg).toContain('without changing anything on it');
    expect(opts.okText).toBe('Allow changes');
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ status: 'writable' });
    await onOk();
    expect(post).toHaveBeenCalledWith('/api/storage/pools/tank/allow-changes', {});
    expect(showToast.mock.calls.at(-1)).toEqual(['“tank” can now be changed.', 'success']);
    post.mockRejectedValueOnce(new Error('tank is in use and could not be reopened: pool is busy'));
    await onOk();
    expect(showToast.mock.calls.at(-1)).toEqual(['tank is in use and could not be reopened: pool is busy', 'error']);
    post.mockRejectedValueOnce(new Error(''));
    await onOk();
    expect(showToast.mock.calls.at(-1)).toEqual(['Could not allow changes', 'error']);
  });

  it('imports a found pool from inside the pool list the same careful way', async () => {
    const tree = box.querySelector('.storage-topology-tree');
    tree.insertAdjacentHTML('beforeend', foundPoolsHtml([{ pool_id: 'usb', fs_type: 'zfs', numeric_id: '99' }]));
    const refusal = Object.assign(new Error('usb was last used by another system.'), { error: 'pool_used_elsewhere' });
    const post = vi.spyOn(api, 'post').mockRejectedValueOnce(refusal).mockRejectedValueOnce(new Error('I/O error'));
    tree.querySelector('.btn-import-external-pool').click();
    await vi.waitFor(() => expect(showDangerConfirm).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith('/api/storage/pools/import', { pool_id: 'usb', fs_type: 'zfs', guid: '99' });
    await showDangerConfirm.mock.calls.at(-1)[2](); // yes, import anyway: and that fails too
    await vi.waitFor(() => expect(showToast.mock.calls.at(-1)).toEqual(['I/O error', 'error']));
  });
});
