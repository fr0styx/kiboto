// New machine presets (VMs decision 5, owner, 16 Nov): "Linux or another system" first, then
// "Windows 11". Each fills the form with what that system needs; every field stays editable.
// Home Assistant comes later: it ships as a disk image, which Kiboto cannot import yet.
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';

/** What each preset sets. ram and vcpus are wishes: the form's limits for this NAS win. */
export const PRESETS = {
  linux: { os: 'linux', vcpus: 2, ram: 4, disk: 32, firmware: 'seabios', tpm: false },
  windows11: { os: 'windows', vcpus: 4, ram: 8, disk: 64, firmware: 'uefi', tpm: true },
};

/** The preset buttons and the note under them. */
export function presetsHtml() {
  const b = (id, title, sub) => `<button type="button" class="vm-preset" data-vm-preset="${id}" aria-pressed="false">
      <strong>${escapeHtml(title)}</strong><span>${escapeHtml(sub)}</span></button>`;
  return `<div class="vm-presets" role="group" aria-label="${escapeHtml(t('vmp.presets', 'Start from'))}">
      ${b('linux', t('vmp.p_linux', 'Linux or another system'), t('vmp.p_linux_2', '2 cores, 4 GB, 32 GB disk'))}
      ${b('windows11', t('vmp.p_win11', 'Windows 11'), t('vmp.p_win11_2', '4 cores, 8 GB, 64 GB disk, UEFI and TPM'))}
    </div>
    <p class="vm-preset-note" id="vm-preset-note" hidden></p>`;
}

/** What to tell someone after choosing a preset. */
export function presetNote(id) {
  if (id === 'windows11') {
    return t('vmp.n_win11', 'Windows 11 needs UEFI and a TPM: both are set. Choose the Windows installer as the boot ISO, and add the driver disc (virtio-win) from the ISO catalog so Windows can see its disk.');
  }
  return t('vmp.n_linux', 'Choose the installer as the boot ISO, or pick one from the ISO catalog.');
}

function setValue(el, value) {
  if (!el) return;
  el.value = String(value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

/**
 * Fills the create form from a preset, inside the limits the form has for this NAS.
 * @param {ParentNode} modal
 * @param {string} id
 */
export function applyPreset(modal, id) {
  const p = PRESETS[id];
  if (!p) return;
  const q = (sel) => /** @type {HTMLInputElement | null} */ (modal.querySelector(sel));
  setValue(q('#vm-create-os'), p.os);
  const ram = q('#vm-create-ram-slider');
  if (ram) setValue(ram, Math.min(p.ram, Number(ram.max) || p.ram));
  const cpu = q('#vm-create-vcpu-slider');
  if (cpu) setValue(cpu, Math.min(p.vcpus, Number(cpu.max) || p.vcpus));
  setValue(q('#vm-create-disk'), p.disk);
  const fw = q(`input[name="vm-create-firmware"][value="${p.firmware}"]`);
  if (fw) {
    fw.checked = true;
    fw.dispatchEvent(new Event('change', { bubbles: true }));
  }
  const tpm = q('#vm-create-tpm');
  if (tpm) {
    tpm.checked = p.tpm;
    tpm.dispatchEvent(new Event('change', { bubbles: true }));
  }
  modal.querySelectorAll('[data-vm-preset]').forEach((b) => b.setAttribute('aria-pressed', /** @type {HTMLElement} */ (b).dataset.vmPreset === id ? 'true' : 'false'));
  const note = /** @type {HTMLElement | null} */ (modal.querySelector('#vm-preset-note'));
  if (note) {
    note.textContent = presetNote(id);
    note.hidden = false;
  }
}

/** Wires the preset buttons of a create form. */
export function bindPresets(modal) {
  modal.querySelectorAll('[data-vm-preset]').forEach((b) => {
    b.addEventListener('click', () => applyPreset(modal, /** @type {HTMLElement} */ (b).dataset.vmPreset || ''));
  });
}
