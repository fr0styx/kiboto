/** NUX-20: Mission Control's host, GPU, NPU, storage and VM telemetry reads as translatable words, with or without details. */
import { describe, it, expect, beforeEach } from 'vitest';
import { updateManagementTelemetry } from '../components/management.js';

const ids = [
  'mgmt-unraid-disks',
  'mgmt-unraid-parity',
  'mgmt-unraid-mover',
  'mgmt-generic-os',
  'mgmt-generic-cpu',
  'mgmt-gpu-line',
  'mgmt-npu-container',
  'mgmt-npu-status-badge',
  'mgmt-npu-name',
  'mgmt-npu-driver',
  'mgmt-npu-node',
  'mgmt-npu-clock',
  'mgmt-npu-accel',
  'mgmt-npu-frameworks-list',
  'mgmt-hub-storage-pill',
  'mgmt-sidebar-storage-badge',
  'mgmt-hub-vms-pill',
  'mgmt-sidebar-vms-badge',
];
const text = (id) => document.getElementById(id).textContent;

describe('Mission Control telemetry words (NUX-20)', () => {
  beforeEach(() => {
    document.body.innerHTML = ids.map((id) => `<div id="${id}"></div>`).join('');
  });

  it('fills in plain words when the host reports little', () => {
    updateManagementTelemetry({
      unraid: { available: true, parity_check: { active: true }, mover: { active: true } },
      cpu: {},
      gpu: { ready: false, codecs: [] },
      npu: { ready: false, frameworks: [] },
      disks: [{}],
      vms: [{ state: 'stopped' }],
    });
    expect(text('mgmt-unraid-disks')).toBe('0 Disks (0 disabled, 0 invalid)');
    expect(text('mgmt-unraid-parity')).toBe('Active (Sync 0%) • 0 Errors');
    expect(text('mgmt-unraid-mover')).toBe('Active (0 files left)');
    expect(text('mgmt-generic-cpu')).toBe('Not reported');
    expect(text('mgmt-gpu-line')).toBe('No graphics chip found');
    expect(text('mgmt-npu-status-badge')).toBe('NPU OFFLINE');
    expect(text('mgmt-npu-name')).toBe('No NPU Detected');
    expect(text('mgmt-npu-driver')).toBe('Driver: none');
    expect(text('mgmt-npu-node')).toBe('No node');
    expect(text('mgmt-npu-clock')).toBe('Dynamic Clock');
    expect(text('mgmt-npu-accel')).toBe('AI Acceleration Ready');
    expect(text('mgmt-npu-frameworks-list')).toBe('CPU Fallback');
    expect(text('mgmt-hub-storage-pill')).toBe('1 Drive');
    expect(text('mgmt-sidebar-storage-badge')).toBe('1 Drive');
    expect(text('mgmt-hub-vms-pill')).toBe('0 Running');
    expect(text('mgmt-sidebar-vms-badge')).toBe('1 VM');
  });

  it('shows the reported details', () => {
    updateManagementTelemetry({
      unraid: {
        available: true,
        disks: { total: 6, disabled: 1, invalid: 0 },
        parity_check: { active: false, errors: 2 },
        mover: { active: false },
      },
      cpu: { cores: 8 },
      gpu: {
        ready: true,
        model: 'Arc',
        driver: 'i915',
        render_node: '/dev/dri/renderD128',
        acceleration: 'QSV',
        codecs: ['AV1'],
      },
      npu: {
        ready: true,
        model: 'AI Boost',
        driver: 'intel_vpu',
        render_node: '/dev/accel/accel0',
        max_freq_mhz: 1400,
        acceleration: 'OpenVINO',
        frameworks: ['ONNX'],
      },
      disks: [{}, {}],
      vms: [{ state: 'running' }, { state: 'stopped' }],
    });
    expect(text('mgmt-unraid-disks')).toBe('6 Disks (1 disabled, 0 invalid)');
    expect(text('mgmt-unraid-parity')).toBe('Completed / Idle • 2 Errors');
    expect(text('mgmt-generic-cpu')).toBe('Not reported · 8 threads');
    expect(text('mgmt-gpu-line')).toBe('Arc · video in hardware: AV1');
    expect(text('mgmt-npu-status-badge')).toBe('NPU ACTIVE');
    expect(text('mgmt-npu-clock')).toBe('1400 MHz');
    expect(text('mgmt-hub-storage-pill')).toBe('2 Drives');
    expect(text('mgmt-hub-vms-pill')).toBe('1 Running');
    expect(text('mgmt-sidebar-vms-badge')).toBe('2 VMs');
    updateManagementTelemetry({
      unraid: {
        available: true,
        parity_check: { active: true, action: 'Check', progress_pct: 40, errors: 1 },
        mover: { active: true, remain_files: 3 },
      },
    });
    expect(text('mgmt-unraid-parity')).toBe('Active (Check 40%) • 1 Error');
    expect(text('mgmt-unraid-mover')).toBe('Active (3 files left)');
  });

  it('names a generic host without details', () => {
    updateManagementTelemetry({ system: {} });
    expect(text('mgmt-generic-os')).toBe('Linux');
    document.body.innerHTML = '';
    expect(() =>
      updateManagementTelemetry({ unraid: { available: true }, gpu: {}, npu: {}, disks: [], vms: [] })
    ).not.toThrow();
  });
});
