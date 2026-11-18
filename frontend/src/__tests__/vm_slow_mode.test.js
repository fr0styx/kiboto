/** VMs decision 4 (a): without hardware virtualization machines start in slow mode, and say so. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { initManagement } from '../components/management.js';
import { isSlow, slowNoteHtml, slowStartText } from '../components/vm/slow-mode.js';

const flush = () => new Promise((r) => setTimeout(r, 30));

describe('slow mode (VMs decision 4 a)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('a running or paused machine started without KVM is slow', () => {
    expect(isSlow({ state: 'running', acceleration: 'tcg' })).toBe(true);
    expect(isSlow({ state: 'paused', acceleration: 'tcg' })).toBe(true);
    expect(isSlow({ state: 'stopped', acceleration: 'tcg' })).toBe(false);
    expect(isSlow({ state: 'running', acceleration: 'kvm' })).toBe(false);
    expect(isSlow(null)).toBe(false);
    expect(slowNoteHtml({ state: 'running', acceleration: 'tcg' }, 'Enable VT-x <in BIOS>')).toContain(
      'title="Enable VT-x &lt;in BIOS&gt;"'
    );
    expect(slowNoteHtml({ state: 'running', acceleration: 'tcg' })).not.toContain('title=');
    expect(slowNoteHtml({ state: 'running', acceleration: 'kvm' })).toBe('');
    expect(slowStartText({ acceleration: 'tcg' }, 'web', 'Enable VT-x.')).toBe(
      "web started in slow mode: this NAS can't use hardware virtualization. Enable VT-x."
    );
    expect(slowStartText({ acceleration: 'tcg' }, 'web')).toBe(
      "web started in slow mode: this NAS can't use hardware virtualization."
    );
    expect(slowStartText({ acceleration: 'kvm' }, 'web')).toBe('');
    expect(slowStartText(null, 'web')).toBe('');
  });

  it('Settings marks the slow machine and shows the fix', async () => {
    document.body.innerHTML = `
      <div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"></div></div></div>
      <div id="mgmt-vms-summary-strip"></div><div id="mgmt-vms-grid"></div><div id="mgmt-vms-empty"></div><div id="mgmt-vms-kvm-body"></div>`;
    const tel = { kvm: { state: 'disabled', remediation: 'Enable VT-x in the BIOS.' } };
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/vms/telemetry') return tel;
      if (url === '/api/vms')
        return [
          { id: 'a', name: 'web', state: 'running', acceleration: 'tcg' },
          { id: 'b', name: 'db', state: 'stopped' },
        ];
      return {};
    });
    try {
      initManagement();
    } catch (_) {
      /* parts of the window this test doesn't build */
    }
    window.dispatchEvent(new Event('vm-updated'));
    await flush();
    const strip = document.getElementById('mgmt-vms-summary-strip')?.textContent || '';
    expect(strip).toContain('Slow mode: no hardware virtualization');
    expect(strip).toContain('Machines still start, slowly. To fix it: Enable VT-x in the BIOS.');
    const cards = [...document.querySelectorAll('.mgmt-vm-card')];
    expect(cards[0].querySelector('.vm-slow-note')?.textContent).toBe('Slow: no hardware virtualization');
    expect(cards[1].querySelector('.vm-slow-note')).toBeNull();
  });
});
