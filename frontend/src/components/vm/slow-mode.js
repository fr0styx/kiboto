/**
 * Slow mode (VMs decision 4 a): on a NAS where Kiboto cannot use hardware virtualization (KVM), a
 * machine still starts, emulated and slowly. The engine records acceleration "tcg"; these say so.
 */
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';

/** A running or paused machine started without hardware virtualization. */
export function isSlow(vm) {
  return !!vm && (vm.state === 'running' || vm.state === 'paused') && vm.acceleration === 'tcg';
}

/** The note under a slow machine's name, with the fix in its tooltip. */
export function slowNoteHtml(vm, fix = '') {
  if (!isSlow(vm)) return '';
  const tip = fix ? ` title="${escapeHtml(fix)}"` : '';
  return `<div class="vm-slow-note" role="note"${tip}>${escapeHtml(t('vms.slow', 'Slow: no hardware virtualization'))}</div>`;
}

/** What to say after Start when the machine came up in slow mode, or "". */
export function slowStartText(res, name, fix = '') {
  if (!res || res.acceleration !== 'tcg') return '';
  const head = t('vms.slow_started', "{name} started in slow mode: this NAS can't use hardware virtualization.", {
    name,
  });
  return fix ? `${head} ${fix}` : head;
}
