// Hardware 3 (hardware report, section 4): the Host tab's facts live on the pages they belong to —
// system, processor, mainboard and graphics on About; the array on Storage; the AI chip on Kib; the
// load on Activity. The live stats fill them wherever they are.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import fs from 'fs';
import path from 'path';
import { updateManagementTelemetry, processorWords, powerModeWord, graphicsWords } from '../components/management.js';

const HTML = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');

const FIXTURE = `
  <div data-host="unraid"><span id="mgmt-unraid-version">-</span></div>
  <div data-host="generic" style="display: none;"><span id="mgmt-generic-os">-</span></div>
  <span id="mgmt-generic-cpu">-</span><span id="mgmt-cpu-gov">-</span>
  <span id="mgmt-board-name">-</span><span id="mgmt-bios-ver">-</span><span id="mgmt-gpu-line">-</span>
  <div class="unraid-details-grid" data-host="unraid">
    <span id="mgmt-unraid-state">-</span><span id="mgmt-unraid-disks">-</span>
    <span id="mgmt-unraid-parity">-</span><span id="mgmt-unraid-mover">-</span>
  </div>
  <div class="unraid-details-grid" data-host="generic" style="display: none;"><span id="mgmt-generic-engine">-</span></div>
  <div id="mgmt-npu-container">
    <span id="mgmt-npu-status-badge">-</span><span id="mgmt-npu-name">-</span><span id="mgmt-npu-driver">-</span>
    <span id="mgmt-npu-node">-</span><span id="mgmt-npu-clock">-</span><span id="mgmt-npu-accel">-</span>
    <div id="mgmt-npu-frameworks-list"></div>
  </div>`;
const text = (id) => document.getElementById(id).textContent;
const shown = (host) => [...document.querySelectorAll(`[data-host="${host}"]`)].every((el) => el.style.display === '');
const hidden = (host) =>
  [...document.querySelectorAll(`[data-host="${host}"]`)].every((el) => el.style.display === 'none');

/** One pane's markup, from its opening tag to the next pane at the same depth (good enough for ids). */
function pane(id, until) {
  const a = HTML.indexOf(`id="${id}"`);
  const b = HTML.indexOf(until, a);
  return HTML.slice(a, b);
}

describe('Hardware 3: facts on their own pages', () => {
  beforeEach(() => {
    document.body.innerHTML = FIXTURE;
  });
  afterEach(() => {
    delete window.openManagementWindow;
  });

  it('on Unraid: the array on Storage, the Unraid version on About, the other host rows hidden', () => {
    updateManagementTelemetry({
      unraid: {
        available: true,
        state: 'STARTED',
        color: 'green-on',
        version: '7.3.2',
        disks: { total: 12 },
        parity_check: { active: false, errors: 0 },
        mover: { active: false },
      },
    });
    expect(shown('unraid')).toBe(true);
    expect(hidden('generic')).toBe(true);
    expect(text('mgmt-unraid-state')).toBe('STARTED');
    expect(text('mgmt-unraid-version')).toBe('Unraid 7.3.2');
    expect(text('mgmt-unraid-disks')).toBe('12 Disks (0 disabled, 0 invalid)');
    expect(text('mgmt-unraid-mover')).toBe('Idle');
    updateManagementTelemetry({ unraid: { available: true } });
    expect(text('mgmt-unraid-state')).toBe('—');
    expect(text('mgmt-unraid-version')).toBe('Unraid');
  });

  it('on another system: its name on About and its storage engine on Storage', () => {
    updateManagementTelemetry({ os: { distro: 'Debian GNU/Linux 13 (trixie)' }, storage: { engine: 'Btrfs' } });
    expect(shown('generic')).toBe(true);
    expect(hidden('unraid')).toBe(true);
    expect(text('mgmt-generic-os')).toBe('Debian GNU/Linux 13 (trixie)');
    expect(text('mgmt-generic-engine')).toBe('Btrfs');
    updateManagementTelemetry({ system: { distro: 'Fedora' } });
    expect(text('mgmt-generic-os')).toBe('Fedora');
    expect(text('mgmt-generic-engine')).toBe('Btrfs / OpenZFS');
  });

  it('processor, power mode, mainboard and BIOS in words', () => {
    updateManagementTelemetry({
      unraid: { available: true },
      cpu: { model: 'Intel(R) Core(TM) Ultra 5 125H', cores: 18, governor: 'powersave' },
      motherboard: { vendor: 'Zettlab', board: 'WY120', bios_version: 'WY120V016', bios_date: '05/09/2026' },
    });
    expect(text('mgmt-generic-cpu')).toBe('Intel Core Ultra 5 125H · 18 threads');
    expect(text('mgmt-cpu-gov')).toBe('Power saving');
    expect(text('mgmt-board-name')).toBe('Zettlab WY120');
    expect(text('mgmt-bios-ver')).toBe('WY120V016 (05/09/2026)');
    updateManagementTelemetry({ motherboard: {} });
    expect(text('mgmt-board-name')).toBe('Standard PC');
    expect(text('mgmt-bios-ver')).toBe('—');
    expect(processorWords({})).toBe('Not reported');
    expect(processorWords({ model: 'ARM Cortex-A76', cores: 1 })).toBe('ARM Cortex-A76 · 1 thread');
    expect(powerModeWord('performance')).toBe('Full speed');
    expect(powerModeWord('schedutil')).toBe('Adjusts to the load');
    expect(powerModeWord('userspace')).toBe('userspace');
    expect(powerModeWord(undefined)).toBe('');
  });

  it('graphics as one line', () => {
    updateManagementTelemetry({ gpu: { ready: true, model: 'Intel Arc Graphics', codecs: ['AV1', 'HEVC', 'H.264'] } });
    expect(text('mgmt-gpu-line')).toBe('Intel Arc Graphics · video in hardware: AV1, HEVC, H.264');
    expect(graphicsWords({ ready: false, model: 'Matrox G200' })).toBe('Matrox G200 · video in software');
    expect(graphicsWords({ ready: true, model: 'Arc', codecs: [] })).toBe('Arc · video in software');
    expect(graphicsWords({})).toBe('No graphics chip found');
    expect(graphicsWords(null)).toBe('No graphics chip found');
  });

  it('the AI chip card is filled on Kib', () => {
    updateManagementTelemetry({
      npu: {
        present: true,
        ready: true,
        model: 'Intel AI Boost NPU',
        driver: 'intel_vpu',
        render_node: '/dev/accel/accel0',
        max_freq_mhz: 1400,
        acceleration: 'OpenVINO',
        frameworks: ['OpenVINO', 'ONNX Runtime'],
      },
    });
    expect(document.getElementById('mgmt-npu-container').style.display).toBe('block');
    expect(text('mgmt-npu-status-badge')).toBe('NPU ACTIVE');
    expect(text('mgmt-npu-driver')).toBe('Driver: intel_vpu');
    expect(text('mgmt-npu-clock')).toBe('1400 MHz');
    expect(document.querySelectorAll('#mgmt-npu-frameworks-list .gpu-codec-tag').length).toBe(2);
  });

  it('the Host tab says where each fact went, and its buttons go there', () => {
    const open = vi.fn();
    window.openManagementWindow = open;
    document.body.innerHTML =
      '<button data-goto-section="mgmt-sec-system-group" data-goto-pane="mgmt-pane-about"><span>About</span></button><button data-goto-section="mgmt-sec-ai">Kib</button><p>else</p>';
    document.querySelector('span').click();
    expect(open).toHaveBeenLastCalledWith('mgmt-sec-system-group', 'mgmt-pane-about');
    document.querySelectorAll('button')[1].click();
    expect(open).toHaveBeenLastCalledWith('mgmt-sec-ai', undefined);
    document.querySelector('p').click();
    expect(open).toHaveBeenCalledTimes(2);
    delete window.openManagementWindow;
    expect(() => document.querySelector('button').click()).not.toThrow();
  });

  it('the window markup: each fact once, on its new page', () => {
    const host = pane('mgmt-pane-unraid', '<!-- Sub-tab 2: Front-panel LCD');
    expect(host).toContain('id="hw-facts-moved"');
    expect(host).not.toMatch(/id="mgmt-(unraid|generic|board|bios|cpu|gpu|npu)-/);
    const about = pane('mgmt-pane-about', '<!-- Observability');
    for (const id of [
      'mgmt-unraid-version',
      'mgmt-generic-os',
      'mgmt-generic-cpu',
      'mgmt-cpu-gov',
      'mgmt-board-name',
      'mgmt-bios-ver',
      'mgmt-gpu-line',
    ]) {
      expect(about).toContain(`id="${id}"`);
    }
    const storage = pane('mgmt-pane-storage-topo', '<!-- Sub-tab 4');
    for (const id of [
      'mgmt-unraid-state',
      'mgmt-unraid-disks',
      'mgmt-unraid-parity',
      'mgmt-unraid-mover',
      'mgmt-generic-engine',
    ]) {
      expect(storage).toContain(`id="${id}"`);
    }
    expect(pane('kib-advanced', '</details>')).toContain('id="mgmt-npu-container"');
    const ids = [...HTML.matchAll(/\sid="(mgmt-(?:unraid|generic|board|bios|cpu|gpu|npu)-[a-z-]+)"/g)].map((m) => m[1]);
    expect(ids.length).toBeGreaterThan(15);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
