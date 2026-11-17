// Five-language sweep: the VM window words the host's KVM and processor state from the server's codes.
import { describe, it, expect, afterEach } from 'vitest';
import { kvmWords, cpuShareWords } from '../components/vm/host-words.js';
import { setLanguage } from '../i18n.js';

describe('VM host state in words', () => {
  afterEach(async () => { await setLanguage('en'); });

  it('every KVM state and processor share has words, in German too', async () => {
    expect(kvmWords({ substate: 'active', badge: 'KVM Accelerated: Active (Intel VT-x)' })).toBe('Fast: hardware virtualization is on');
    for (const s of ['container_restricted', 'module_missing', 'restricted', 'bios_disabled']) expect(kvmWords({ substate: s })).toMatch(/^Slow: /);
    expect(kvmWords({ substate: 'new_state', badge: 'Something new' })).toBe('Something new');
    expect(kvmWords(null)).toBe('Fast: hardware virtualization is on');
    expect(cpuShareWords({ status: 'moderate_overcommit', overcommit_ratio: 1.5 })).toBe('Processors shared: 1.5×');
    expect(cpuShareWords({ status: 'heavy_overcommit', overcommit_ratio: 3 })).toBe('Processors heavily shared: 3×');
    expect(cpuShareWords({ overcommit_ratio: 2 })).toBe('2×');
    expect(cpuShareWords({})).toBe('');
    expect(cpuShareWords({ status: 'moderate_overcommit' })).toBe('');
    expect(cpuShareWords({ status: 'heavy_overcommit', badge: 'Heavy' })).toBe('Heavy');
    expect(cpuShareWords(null)).toBe('');
    await setLanguage('de');
    expect(kvmWords({ substate: 'bios_disabled' })).toBe('Langsam: Virtualisierung ist im BIOS ausgeschaltet');
    expect(cpuShareWords({ status: 'nominal', overcommit_ratio: 0.5 })).toBe('Jeder virtuelle Prozessor hat einen eigenen Thread');
  });
});
