/**
 * VMs report 35: the VM dialogs announce themselves as dialogs, take the focus to their first field
 * (it landed on "Minimize"), close on Escape, and Create and Edit ask before Escape throws a changed
 * form away. Create and Edit can be minimised, so they are not aria-modal.
 */
import { t } from '../../i18n.js';
import { showConfirmToast } from '../../toast.js';

const FIRST = 'input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled]), .smart-modal-body button:not([disabled])';

/** Marks the dialog, focuses its first field, starts change tracking; Escape presses its Close. */
export function asDialog(backdrop, { modal = true, escape = true } = {}) {
  if (!backdrop) return null;
  const win = /** @type {HTMLElement} */ (backdrop.querySelector('.smart-modal-window') || backdrop);
  const title = backdrop.querySelector('.smart-modal-title');
  if (title && !title.id) title.id = `${backdrop.id || 'vm-dialog'}-title`;
  win.setAttribute('role', 'dialog');
  if (modal) win.setAttribute('aria-modal', 'true');
  if (title) win.setAttribute('aria-labelledby', title.id);
  backdrop.dataset.dirty = '';
  if (!backdrop.dataset.a11yWired) {
    backdrop.dataset.a11yWired = '1';
    backdrop.addEventListener('input', () => { backdrop.dataset.dirty = '1'; });
    if (escape) {
      backdrop.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape' || backdrop.style.display === 'none') return;
        e.preventDefault();
        e.stopPropagation();
        /** @type {HTMLElement | null} */ (backdrop.querySelector('.win-btn.close-btn, .close-btn'))?.click();
      });
    }
  }
  const first = /** @type {HTMLElement | null} */ (backdrop.querySelector(FIRST));
  first?.focus();
  return win;
}

/** Escape on Create or Edit: closes at once when nothing changed, else asks first. */
export function askBeforeDiscard(backdrop, close) {
  if (backdrop?.dataset.dirty !== '1') {
    close();
    return false;
  }
  showConfirmToast(t('vmd.discard_q', 'Close without saving? Your changes are lost.'), () => close());
  return true;
}
