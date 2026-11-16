/** VMs report 25: a running machine's processors and memory can't change (the server refuses); the
 *  edit dialog says so and locks those two sliders instead of promising a later restart. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { vmState } from '../components/vm/state.js';
import { openVmEditModal } from '../components/vm/edit-modal.js';

const flush = () => new Promise((r) => setTimeout(r, 30));

describe('VM edit on a running machine (VMs report 25)', () => {
  afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = ''; vmState.list = []; });

  async function open(state) {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/vms/telemetry') return { memory_budget: { safe_slider_max_gb: 16 }, cpu_capacity: { host_threads: 8 } };
      if (url.startsWith('/api/vms/isos')) return [];
      return {};
    });
    vmState.telemetry = { memory_budget: { safe_slider_max_gb: 16 }, cpu_capacity: { host_threads: 8 } };
    vmState.list = [{ id: 'v1', name: 'web', state, vcpus: 2, ram_gb: 4 }];
    openVmEditModal('v1');
    await flush();
  }

  it('says processors and memory need a shut-down, and locks them', async () => {
    await open('running');
    expect(document.body.textContent).toContain('Shut it down to change its processors or memory.');
    expect(document.body.textContent).not.toContain('take effect when it next restarts');
    expect(/** @type {HTMLInputElement} */ (document.getElementById('vm-edit-vcpu-slider')).disabled).toBe(true);
    expect(/** @type {HTMLInputElement} */ (document.getElementById('vm-edit-ram-slider')).disabled).toBe(true);
  });

  it('a stopped machine can change both', async () => {
    await open('stopped');
    expect(document.body.textContent).not.toContain('Shut it down');
    expect(/** @type {HTMLInputElement} */ (document.getElementById('vm-edit-vcpu-slider')).disabled).toBe(false);
    expect(/** @type {HTMLInputElement} */ (document.getElementById('vm-edit-ram-slider')).disabled).toBe(false);
  });
});
