// A new virtual machine in three steps (SET-29, VMs report stage 3): What to install, How big, More.
// The form keeps every field; each block carries the step it belongs to, and the dialog shows one
// step at a time with Back and Next. Create is on the last step.
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';

export const STEPS = 3;
const NAME_RE = /^[a-zA-Z0-9_-]{2,64}$/;

/** The step names, in order. */
export function stepNames() {
  return [t('vmst.what', 'What to install'), t('vmst.size', 'How big'), t('vmst.more', 'More')];
}

/** The step list at the top of the dialog. */
export function stepsHtml() {
  return `<ol class="vm-steps" aria-label="${escapeHtml(t('vmst.steps', 'Steps'))}">${stepNames()
    .map((name, i) => `<li data-vm-step-label="${i + 1}"><span class="vm-step-n" aria-hidden="true">${i + 1}</span> ${escapeHtml(name)}</li>`)
    .join('')}</ol>`;
}

/** Whether the name is one the server takes; says why not next to the field. */
export function checkName(modal) {
  const input = /** @type {HTMLInputElement | null} */ (modal.querySelector('#vm-create-name'));
  const ok = NAME_RE.test(String(input?.value || '').trim());
  if (input) input.setAttribute('aria-invalid', ok ? 'false' : 'true');
  modal.querySelector('#vm-create-name-rule')?.classList.toggle('is-wrong', !ok);
  if (!ok) input?.focus();
  return ok;
}

/**
 * Shows one step: its blocks, its name marked in the list, Back and Next or Create.
 * @param {HTMLElement} modal
 * @param {number} n
 */
export function showStep(modal, n) {
  const step = Math.min(STEPS, Math.max(1, n));
  modal.dataset.vmAt = String(step);
  modal.querySelectorAll('[data-vm-step-label]').forEach((li) => {
    const on = /** @type {HTMLElement} */ (li).dataset.vmStepLabel === String(step);
    if (on) li.setAttribute('aria-current', 'step');
    else li.removeAttribute('aria-current');
  });
  const back = /** @type {HTMLElement | null} */ (modal.querySelector('#vm-create-back'));
  const next = /** @type {HTMLElement | null} */ (modal.querySelector('#vm-create-next'));
  const create = /** @type {HTMLElement | null} */ (modal.querySelector('#vm-create-submit'));
  if (back) back.hidden = step === 1;
  if (next) next.hidden = step === STEPS;
  if (create) create.hidden = step !== STEPS;
  const first = /** @type {HTMLElement | null} */ (modal.querySelector(`[data-vm-step="${step}"] input:not([type="hidden"]), [data-vm-step="${step}"] select, [data-vm-step="${step}"] button`));
  first?.focus();
  return step;
}

/** Wires Back and Next; Next from the first step needs a name the server takes. */
export function installSteps(modal) {
  const footer = modal.querySelector('.smart-modal-footer');
  const create = modal.querySelector('#vm-create-submit');
  if (footer && create && !modal.querySelector('#vm-create-next')) {
    create.insertAdjacentHTML('beforebegin', `<button type="button" id="vm-create-back" class="btn-pill-toggle">${escapeHtml(t('vmst.back', 'Back'))}</button><button type="button" id="vm-create-next" class="btn-pill-toggle is-primary">${escapeHtml(t('vmst.next', 'Next'))}</button>`);
  }
  modal.querySelector('#vm-create-back')?.addEventListener('click', () => showStep(modal, Number(modal.dataset.vmAt || 1) - 1));
  modal.querySelector('#vm-create-next')?.addEventListener('click', () => {
    const step = Number(modal.dataset.vmAt || 1);
    if (step === 1 && !checkName(modal)) return;
    showStep(modal, step + 1);
  });
  modal.querySelector('#vm-create-name')?.addEventListener('input', () => {
    if (modal.querySelector('#vm-create-name')?.getAttribute('aria-invalid') === 'true') checkName(modal);
  });
  return showStep(modal, 1);
}
