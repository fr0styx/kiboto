// The host's KVM and processor-sharing state in the reader's language, from the server's codes
// (its badge texts are English; found by the five-language sweep).
import { t } from '../../i18n.js';

/** @param {{substate?: string, badge?: string} | null | undefined} kvm */
export function kvmWords(kvm) {
  switch (kvm?.substate) {
    case 'active': return t('vmh.kvm_active', 'Fast: hardware virtualization is on');
    case 'container_restricted': return t('vmh.kvm_container', "Slow: the NAS supports it, but Kiboto's container may not use it");
    case 'module_missing': return t('vmh.kvm_module', 'Slow: the virtualization module is not loaded');
    case 'restricted': return t('vmh.kvm_restricted', 'Slow: virtualization is not available to Kiboto');
    case 'bios_disabled': return t('vmh.kvm_bios', 'Slow: virtualization is switched off in the BIOS');
    default: return kvm?.badge || t('vmh.kvm_active', 'Fast: hardware virtualization is on');
  }
}

/** @param {{status?: string, badge?: string, overcommit_ratio?: number} | null | undefined} cpu */
export function cpuShareWords(cpu) {
  const ratio = typeof cpu?.overcommit_ratio === 'number' ? cpu.overcommit_ratio : null;
  if (cpu?.status === 'nominal') return t('vmh.cpu_nominal', 'Each virtual processor has a thread of its own');
  if (cpu?.status === 'moderate_overcommit' && ratio !== null) return t('vmh.cpu_shared', 'Processors shared: {ratio}×', { ratio });
  if (cpu?.status === 'heavy_overcommit' && ratio !== null) return t('vmh.cpu_heavy', 'Processors heavily shared: {ratio}×', { ratio });
  return cpu?.badge || (ratio !== null ? `${ratio}×` : '');
}
