/** VMs decision 5: a new machine starts from "Linux or another system" or "Windows 11". */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { PRESETS, presetsHtml, presetNote, applyPreset, bindPresets } from '../components/vm/presets.js';

const FORM = `<form>
  <select id="vm-create-os"><option value="linux">Linux</option><option value="windows">Windows</option></select>
  <input type="range" id="vm-create-ram-slider" min="0.5" max="6" step="0.5" value="4">
  <input type="range" id="vm-create-vcpu-slider" min="1" max="8" value="2">
  <input type="number" id="vm-create-disk" value="32">
  <input type="radio" name="vm-create-firmware" value="seabios" checked><input type="radio" name="vm-create-firmware" value="uefi">
  <input type="checkbox" id="vm-create-tpm">
</form>`;

describe('new machine presets (VMs decision 5)', () => {
  beforeEach(() => { document.body.innerHTML = presetsHtml() + FORM; });

  it('offers Linux first, then Windows 11, and no Home Assistant yet', () => {
    const ids = [...document.querySelectorAll('[data-vm-preset]')].map((b) => b.dataset.vmPreset);
    expect(ids).toEqual(['linux', 'windows11']);
    expect(document.body.textContent).toContain('Linux or another system');
    expect(document.body.textContent).toContain('4 cores, 8 GB, 64 GB disk, UEFI and TPM');
    expect(Object.keys(PRESETS)).toEqual(['linux', 'windows11']);
  });

  it('Windows 11 sets UEFI, TPM and its sizes, inside this NAS\'s limits', () => {
    const ram = document.getElementById('vm-create-ram-slider');
    const heard = vi.fn();
    ram.addEventListener('input', heard);
    bindPresets(document);
    document.querySelector('[data-vm-preset="windows11"]').click();
    expect(document.getElementById('vm-create-os').value).toBe('windows');
    expect(ram.value).toBe('6'); // 8 GB wished, 6 GB is this NAS's safe maximum
    expect(heard).toHaveBeenCalled(); // the form's own displays update
    expect(document.getElementById('vm-create-vcpu-slider').value).toBe('4');
    expect(document.getElementById('vm-create-disk').value).toBe('64');
    expect(document.querySelector('input[value="uefi"]').checked).toBe(true);
    expect(document.getElementById('vm-create-tpm').checked).toBe(true);
    expect(document.querySelector('[data-vm-preset="windows11"]').getAttribute('aria-pressed')).toBe('true');
    expect(document.getElementById('vm-preset-note').hidden).toBe(false);
    expect(document.getElementById('vm-preset-note').textContent).toContain('virtio-win');
  });

  it('Linux puts it back, and an unknown preset or a bare form changes nothing', () => {
    applyPreset(document, 'windows11');
    applyPreset(document, 'linux');
    expect(document.getElementById('vm-create-os').value).toBe('linux');
    expect(document.querySelector('input[value="seabios"]').checked).toBe(true);
    expect(document.getElementById('vm-create-tpm').checked).toBe(false);
    expect(document.getElementById('vm-preset-note').textContent).toBe(presetNote('linux'));
    applyPreset(document, 'haos');
    expect(document.getElementById('vm-create-os').value).toBe('linux');
    const bare = document.createElement('div');
    applyPreset(bare, 'windows11');
    expect(bare.innerHTML).toBe('');
  });
});
