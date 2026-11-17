/** VMs report 34: phone layout, arrow keys for installers, no "undefined" in the VM window. */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const src = (p) => readFileSync(resolve(__dirname, '..', p), 'utf8');

describe('VMs on a phone (VMs report 34)', () => {
  it('the button rows wrap and VM buttons get 44 px targets', () => {
    const css = src('styles/25-mobile-ergonomics.css');
    expect(css).toContain('#mgmt-pane-vms-list .vml-row-2 { flex-wrap: wrap; }');
    expect(css).toContain('#vm-manager-window button, .vm-manager-window button { min-height: 44px; }');
    expect(css).toMatch(/\.vm-action-btns-wrap \{\n\s+display: flex !important;\n\s+flex-wrap: wrap !important;/);
  });

  it('the phone key sheet has the arrows and Enter', () => {
    const c = src('components/vm/console.js');
    for (const k of ["'ArrowUp'", "'ArrowDown'", "'ArrowLeft'", "'ArrowRight'", "_sendKeyToRfb(0xff0d, 'Enter')"]) expect(c).toContain(k);
  });

  it('missing numbers show a dash, not "undefined"', () => {
    const v = src('components/vm-manager.js');
    expect(v).toContain("typeof mem.safe_max_vm_ram_gb === 'number'");
    expect(src('components/vm/host-words.js')).toContain("typeof cpu?.overcommit_ratio === 'number'");
    expect(v).toContain('vm.disk_size_gb != null');
    expect(v).toContain('elRatioBadge.hidden = !elRatioBadge.textContent');
  });
});
