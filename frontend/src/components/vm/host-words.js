// The host's KVM and processor-sharing state in the reader's language, from the server's codes
// (its badge texts are English; found by the five-language sweep).
import { t } from '../../i18n.js';

/** @param {{substate?: string, badge?: string} | null | undefined} kvm */
export function kvmWords(kvm) {
  switch (kvm?.substate) {
    case 'active':
      return t('vmh.kvm_active', 'Fast: hardware virtualization is on');
    case 'container_restricted':
      return t('vmh.kvm_container', "Slow: the NAS supports it, but Kiboto's container may not use it");
    case 'module_missing':
      return t('vmh.kvm_module', 'Slow: the virtualization module is not loaded');
    case 'restricted':
      return t('vmh.kvm_restricted', 'Slow: virtualization is not available to Kiboto');
    case 'bios_disabled':
      return t('vmh.kvm_bios', 'Slow: virtualization is switched off in the BIOS');
    default:
      return kvm?.badge || t('vmh.kvm_active', 'Fast: hardware virtualization is on');
  }
}

/** @param {{status?: string, badge?: string, overcommit_ratio?: number} | null | undefined} cpu */
export function cpuShareWords(cpu) {
  const ratio = typeof cpu?.overcommit_ratio === 'number' ? cpu.overcommit_ratio : null;
  if (cpu?.status === 'nominal') return t('vmh.cpu_nominal', 'Each virtual processor has a thread of its own');
  if (cpu?.status === 'moderate_overcommit' && ratio !== null)
    return t('vmh.cpu_shared', 'Processors shared: {ratio}×', { ratio });
  if (cpu?.status === 'heavy_overcommit' && ratio !== null)
    return t('vmh.cpu_heavy', 'Processors heavily shared: {ratio}×', { ratio });
  return cpu?.badge || (ratio !== null ? `${ratio}×` : '');
}

/** What to do about a slow KVM state, in the reader's language (commands kept as they are). */
export function kvmFix(kvm) {
  switch (kvm?.substate) {
    case 'container_restricted':
      return t(
        'vmh.fix_container',
        "The NAS supports it, but Kiboto's container may not open /dev/kvm. On Unraid, add \u201c--device /dev/kvm\u201d to Extra Parameters in Kiboto's container template; with Docker Compose, add devices: ['/dev/kvm:/dev/kvm'] and device_cgroup_rules: ['c 10:232 rwm']."
      );
    case 'module_missing':
      return t(
        'vmh.fix_module',
        'Load the KVM module on the host: run \u201cmodprobe kvm_intel\u201d (or \u201cmodprobe kvm_amd\u201d).'
      );
    case 'restricted':
      return t('vmh.fix_restricted', 'Make sure /dev/kvm exists on the host and Kiboto may read and write it.');
    case 'bios_disabled':
      return t('vmh.fix_bios', 'Restart the NAS and switch on Intel VT-x or AMD SVM in its BIOS or UEFI settings.');
    default:
      return kvm?.remediation || '';
  }
}
