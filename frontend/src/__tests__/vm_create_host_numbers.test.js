/** VMs report 18: the new-machine dialog uses this NAS's numbers, fetched when the VM window has not. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { vmState } from '../components/vm/state.js';
import { openVmCreateModal } from '../components/vm/create-modal.js';

const flush = () => new Promise((r) => setTimeout(r, 20));

describe('new machine from Settings (VMs report 18)', () => {
  afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = ''; vmState.telemetry = null; });

  it('fetches the host numbers first and shows them', async () => {
    vmState.telemetry = null;
    const get = vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/vms/telemetry') return { memory_budget: { safe_slider_max_gb: 11, override_max_ram_gb: 15 }, cpu_capacity: { host_threads: 4 } };
      return [];
    });
    await openVmCreateModal();
    await flush();
    expect(get).toHaveBeenCalledWith('/api/vms/telemetry');
    expect(document.getElementById('vm-slider-max-label')?.textContent).toBe('Safe max: 11 GB');
    expect(document.body.textContent).not.toContain('Safe max: 28 GB');
  });

  it('says the limit is not known when the server does not answer', async () => {
    vmState.telemetry = null;
    vi.spyOn(api, 'get').mockImplementation(async (url) => { if (url === '/api/vms/telemetry') throw new Error('down'); return []; });
    await openVmCreateModal();
    await flush();
    expect(document.getElementById('vm-slider-max-label')?.textContent).toContain('is not known');
  });
});
