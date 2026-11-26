/** NUX-20: Mission Control's virtual machines pane reads as translatable words. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { initManagement } from '../components/management.js';
import { api } from '../api.js';

const flush = () => new Promise((r) => setTimeout(r, 20));

describe('Mission Control VM pane (NUX-20)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('labels the summary, the VM cards and the KVM details', async () => {
    document.body.innerHTML = `
      <div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"></div></div></div>
      <span id="mgmt-hub-vms-pill"></span><span id="mgmt-sidebar-vms-badge"></span>
      <div id="mgmt-vms-summary-strip"></div><div id="mgmt-vms-grid"></div><div id="mgmt-vms-empty"></div><div id="mgmt-vms-kvm-body"></div>`;
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/vms/telemetry')
        return {
          kvm: { state: 'active' },
          cpu_capacity: { host_threads: 8, allocated_vcpus: 2 },
          memory_budget: { safe_headroom_gb: 20.5 },
          vhost_net: true,
          bridges: ['br0'],
        };
      if (url === '/api/vms')
        return [
          { id: 'a', name: 'web', state: 'running', vcpus: 2, ram_gb: 4 },
          { id: 'b', name: 'db', state: 'stopped' },
        ];
      return {};
    });
    vi.spyOn(api, 'post').mockResolvedValue({});
    try {
      initManagement();
    } catch (_) {
      /* parts of the window this test doesn't build */
    }
    window.dispatchEvent(new Event('vm-updated'));
    await flush();
    const text = document.body.textContent;
    expect(document.getElementById('mgmt-hub-vms-pill').textContent).toBe('1 Running');
    expect(document.getElementById('mgmt-sidebar-vms-badge').textContent).toBe('2 VMs');
    for (const w of [
      'Hypervisor',
      'Memory left for machines',
      '20.5 GB',
      'Processor threads in use',
      '2 of 8',
      'Running',
      'Stopped',
      'Hardware Virtualization Extension',
      'CPU Host Threads',
      '8 Threads',
      'vhost-net Acceleration',
      'Supported',
      'Network bridges',
      'br0',
    ]) {
      expect(text).toContain(w);
    }
    // VMs decision 2: Settings shows status; the buttons are in the VM window only
    expect(
      document.querySelector('.btn-vm-action-start, .btn-vm-action-stop, .btn-vm-action-console, .btn-vm-action-edit')
    ).toBeNull();
    const lines = [...document.querySelectorAll('.mgmt-vm-line')];
    expect(lines.map((l) => l.querySelector('.mgmt-vm-state').textContent)).toEqual(['Running', 'Stopped']);
    expect(lines[0].textContent).toContain('2 vCPU • 4 GB RAM');
    const launch = document.createElement('button');
    launch.id = 'btn-mgmt-vm-launch-window';
    const opened = vi.fn();
    launch.addEventListener('click', opened);
    document.body.appendChild(launch);
    /** @type {HTMLButtonElement} */ (document.getElementById('mgmt-vms-open-window')).click();
    expect(opened).toHaveBeenCalledTimes(1);
  });

  it('still renders without the hub pill, and for a VM without a name', async () => {
    document.body.innerHTML = `
      <div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"></div></div></div>
      <div id="mgmt-vms-summary-strip"></div><div id="mgmt-vms-grid"></div><div id="mgmt-vms-empty"></div><div id="mgmt-vms-kvm-body"></div>`;
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url === '/api/vms'
        ? [
            { id: 'vm-x', state: 'running' },
            { id: 'p', state: 'paused', memory_mb: 512, os_family: 'windows' },
            { id: 'g', state: 'stopped', memory_mb: 2048, os_type: 'Other' },
            { id: 's', state: 'shutting_down' },
          ]
        : {}
    );
    try {
      initManagement();
    } catch (_) {
      /* as above */
    }
    window.dispatchEvent(new Event('vm-updated'));
    await flush();
    const lines = [...document.querySelectorAll('.mgmt-vm-line')];
    expect(lines[0].textContent).toContain('vm-x');
    expect(lines[0].textContent).toContain('Linux • 1 vCPU • 1 GB RAM');
    expect(lines[1].textContent).toContain('Windows • 1 vCPU • 512 MB RAM');
    expect(lines[1].querySelector('.mgmt-vm-state').textContent).toBe('Paused');
    expect(lines[2].textContent).toContain('Other • 1 vCPU • 2 GB RAM');
    // without the launch button in the page the open control does nothing rather than throw
    /** @type {HTMLButtonElement} */ (document.getElementById('mgmt-vms-open-window')).click();
  });

  it('leaves out what the server did not say instead of making it up (VMs report 15-17)', async () => {
    document.body.innerHTML = `
      <div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"></div></div></div>
      <div id="mgmt-vms-summary-strip"></div><div id="mgmt-vms-grid"></div><div id="mgmt-vms-empty"></div><div id="mgmt-vms-kvm-body"></div>`;
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/vms/telemetry') return { kvm: { state: 'active' }, vhost_net: false, bridges: [] };
      if (url === '/api/vms') return [];
      return {};
    });
    try {
      initManagement();
    } catch (_) {
      /* as above */
    }
    window.dispatchEvent(new Event('vm-updated'));
    await flush();
    const text = document.body.textContent;
    for (const w of [
      'Dynamic',
      'Optimal',
      'Memory left',
      'Processor threads',
      'Threads',
      'near bare-metal',
      'virbr0',
    ]) {
      expect(text).not.toContain(w);
    }
    expect(text).toContain('Not available');
    expect(text).toContain('None found');
  });

  it('a failed list says so with Try again, not "No Virtual Machines Found" (VMs report 16)', async () => {
    document.body.innerHTML = `
      <div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"></div></div></div>
      <div id="mgmt-vms-summary-strip"></div><div id="mgmt-vms-grid"></div><div id="mgmt-vms-empty" style="display:none">No Virtual Machines Found</div><div id="mgmt-vms-kvm-body"></div>`;
    const get = vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/vms') throw new Error('403 Forbidden');
      throw new Error('down');
    });
    try {
      initManagement();
    } catch (_) {
      /* as above */
    }
    window.dispatchEvent(new Event('vm-updated'));
    await flush();
    const grid = /** @type {HTMLElement} */ (document.getElementById('mgmt-vms-grid'));
    expect(grid.textContent).toContain('The virtual machines could not be loaded.');
    expect(grid.textContent).toContain('403 Forbidden');
    expect(/** @type {HTMLElement} */ (document.getElementById('mgmt-vms-empty')).style.display).toBe('none');
    const strip = /** @type {HTMLElement} */ (document.getElementById('mgmt-vms-summary-strip'));
    expect(strip.textContent).toContain('Could not be checked');
    expect(strip.textContent).not.toContain('Software Emulation');
    const calls = get.mock.calls.length;
    /** @type {HTMLButtonElement} */ (grid.querySelector('#mgmt-vms-retry')).click();
    await flush();
    expect(get.mock.calls.length).toBeGreaterThan(calls);
  });

  it('names each speed-up state, and copes without an error message or an empty block', async () => {
    const strip = () =>
      /** @type {HTMLElement} */ (document.getElementById('mgmt-vms-summary-strip')).textContent || '';
    const cases = [
      [{ kvm: { state: 'active' } }, 'KVM Acceleration Active'],
      [
        { kvm: { state: 'restricted', badge: 'Docker cgroup restricted', remediation: 'Add --device /dev/kvm.' } },
        'Slow mode: no hardware virtualization',
      ],
      [{ kvm: { state: 'missing' } }, 'Slow mode: no hardware virtualization'],
      [{}, 'Could not be checked'],
    ];
    for (const [tel, word] of cases) {
      vi.restoreAllMocks();
      document.body.innerHTML = `
        <div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"></div></div></div>
        <div id="mgmt-vms-summary-strip"></div><div id="mgmt-vms-grid"></div><div id="mgmt-vms-kvm-body"></div>`;
      vi.spyOn(api, 'get').mockImplementation(async (url) => {
        if (url === '/api/vms/telemetry') return tel;
        throw null; // a rejection without an error object
      });
      try {
        initManagement();
      } catch (_) {
        /* as above */
      }
      window.dispatchEvent(new Event('vm-updated'));
      await flush();
      expect(strip()).toContain(word);
      expect(document.getElementById('mgmt-vms-grid')?.textContent).toContain(
        'The virtual machines could not be loaded.'
      );
    }
  });
});
