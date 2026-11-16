/** VMs report 25: a running machine's processors and memory can't change (the server refuses); the
 *  edit dialog says so and locks those two sliders instead of promising a later restart. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import * as toast from '../toast.js';
import { vmState } from '../components/vm/state.js';
import { openVmEditModal } from '../components/vm/edit-modal.js';

const flush = () => new Promise((r) => setTimeout(r, 30));
/** @type {any} */
let usbDevs = [];

describe('VM edit on a running machine (VMs report 25)', () => {
  afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = ''; vmState.list = []; });

  async function open(state) {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/vms/telemetry') return { memory_budget: { safe_slider_max_gb: 16 }, cpu_capacity: { host_threads: 8 } };
      if (url.startsWith('/api/vms/isos')) return [];
      if (url === '/api/vms/usb-devices') return usbDevs;
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

  it("its USB list leaves out the NAS's root hubs (VMs report 26)", async () => {
    usbDevs = [null, { vendor_id: '1d6b', product_id: '0002', description: 'Root Hub (1)', is_root_hub: true }, { vendor_id: '0bda', product_id: '8153', description: 'USB Ethernet' }, { vendor_id: '1234', product_id: '5678', product: 'Game Pad' }];
    await open('stopped');
    const opts = [...document.querySelectorAll('select option')].map((o) => o.textContent || '');
    expect(opts.some((o) => o.includes('USB Ethernet'))).toBe(true);
    expect(opts.some((o) => o.includes('Root Hub'))).toBe(false);
    expect(opts.some((o) => o.includes('Game Pad'))).toBe(true);
  });

  it('only root hubs, or no list at all, means no devices to offer', async () => {
    for (const devs of [[{ vendor_id: '1d6b', product_id: '0003', is_root_hub: true }], { error: 'x' }]) {
      document.body.innerHTML = '';
      usbDevs = devs;
      await open('stopped');
      expect(document.body.textContent).toContain('No USB devices found');
      vi.restoreAllMocks();
    }
  });

  it('marks a USB drive the NAS uses and asks before adding it (VMs report 26)', async () => {
    usbDevs = [{ vendor_id: '0781', product_id: '5583', description: 'SanDisk', nas_use: 'storage' }];
    const ask = vi.spyOn(toast, 'showConfirmToast').mockImplementation((msg, ok) => ok());
    await open('stopped');
    const sel = /** @type {HTMLSelectElement} */ (document.querySelector('#vm-edit-host-usb-select'));
    const drive = [...sel.options].find((o) => o.textContent?.includes('SanDisk'));
    expect(drive?.textContent).toContain('(used by this NAS: a USB drive)');
    sel.value = drive?.value || '';
    /** @type {HTMLButtonElement} */ (document.querySelector('#btn-edit-add-usb-device')).click();
    expect(ask.mock.calls.at(-1)?.[0]).toContain('boot drive');
    /** @type {HTMLButtonElement} */ (document.querySelector('#btn-edit-add-usb-device')).click();
  });
});

