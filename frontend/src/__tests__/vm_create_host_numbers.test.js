/** VMs report 18: the new-machine dialog uses this NAS's numbers, fetched when the VM window has not. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import * as toast from '../toast.js';
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

  it("the USB list leaves out the NAS's root hubs (VMs report 26)", async () => {
    vmState.telemetry = { memory_budget: { safe_slider_max_gb: 8 }, cpu_capacity: { host_threads: 4 } };
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/vms/usb-devices') return [
        { vendor_id: '1d6b', product_id: '0002', description: 'Root Hub (1)', is_root_hub: true },
        { vendor_id: '046d', product_id: 'c52b', description: 'Logitech Receiver' },
        null,
        { vendor_id: '1234', product_id: '5678', product: 'Game Pad' },
      ];
      return [];
    });
    await openVmCreateModal();
    await flush();
    const opts = [...document.querySelectorAll('#modal-vm-create select option')].map((o) => o.textContent || '');
    expect(opts.some((o) => o.includes('Logitech Receiver'))).toBe(true);
    expect(opts.some((o) => o.includes('Root Hub'))).toBe(false);
    expect(opts.some((o) => o.includes('Game Pad'))).toBe(true);
  });

  it('only root hubs means no devices to offer', async () => {
    vmState.telemetry = { memory_budget: { safe_slider_max_gb: 8 }, cpu_capacity: { host_threads: 4 } };
    for (const devs of [[{ vendor_id: '1d6b', product_id: '0003', is_root_hub: true }], { error: 'x' }]) {
      vi.restoreAllMocks();
      vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/vms/usb-devices' ? devs : []));
      await openVmCreateModal();
      await flush();
      expect(document.getElementById('modal-vm-create')?.textContent).toContain('No USB devices found');
    }
  });

  it('marks the UPS the NAS uses and asks before adding it (VMs report 26)', async () => {
    vmState.telemetry = { memory_budget: { safe_slider_max_gb: 8 }, cpu_capacity: { host_threads: 4 } };
    vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/vms/usb-devices'
      ? [{ vendor_id: '051d', product_id: '0002', description: 'APC UPS', nas_use: 'ups' }, { vendor_id: '046d', product_id: 'c52b', description: 'Receiver' }] : []));
    const ask = vi.spyOn(toast, 'showConfirmToast').mockImplementation((msg, ok) => ok());
    await openVmCreateModal();
    await flush();
    const sel = /** @type {HTMLSelectElement} */ (document.querySelector('#vm-create-host-usb-select'));
    const ups = [...sel.options].find((o) => o.textContent?.includes('APC UPS'));
    expect(ups?.textContent).toContain('(used by this NAS: the UPS)');
    sel.value = ups?.value || '';
    /** @type {HTMLButtonElement} */ (document.querySelector('#btn-create-add-usb-device')).click();
    expect(ask).toHaveBeenCalled();
    expect(document.body.textContent).toContain('APC UPS');
    /** @type {HTMLButtonElement} */ (document.querySelector('#btn-create-add-usb-device')).click(); // already there
  });
});

