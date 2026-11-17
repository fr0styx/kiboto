// Drive Health's roles and Spotlight's result kinds in the reader's language (five-language sweep, 17 Nov).
import { describe, it, expect, afterEach } from 'vitest';
import { roleWord, shownSerial } from '../components/drive-health.js';
import { categoryWord } from '../components/spotlight.js';
import { setLanguage } from '../i18n.js';

describe('words on Drive Health and Spotlight', () => {
  afterEach(async () => { await setLanguage('en'); });

  it('roles, serials and kinds', async () => {
    expect(roleWord('os')).toBe('system');
    expect(roleWord('mystery')).toBe('mystery');
    expect(roleWord(undefined)).toBe('');
    expect(shownSerial('Unknown')).toBe('');
    expect(shownSerial('WD-123')).toBe('WD-123');
    expect(shownSerial(null)).toBe('');
    expect(shownSerial('Unknown (Standby)')).toBe('');
    expect(shownSerial(1234)).toBe(1234);
    expect(categoryWord(undefined)).toBe('action');
    expect(categoryWord('other')).toBe('other');
    await setLanguage('de');
    expect(roleWord('data')).toBe('Daten');
    expect(categoryWord('setting')).toBe('Einstellung');
  });
});
