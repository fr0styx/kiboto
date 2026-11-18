// The Settings sweep of 18 Nov: the Appearance slider scales, the desktop preview label, the UPS state
// and the "in use" badges were English in every language.
import { describe, it, expect, afterEach } from 'vitest';
import fs from 'fs';
import path from 'path';
import { upsStateWord } from '../components/management/ups.js';
import { setLanguage } from '../i18n.js';

const MW = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');

describe('Settings sweep words (18 Nov)', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('the slider scales and the preview label carry their keys', () => {
    for (const k of [
      'gls.dim_0',
      'gls.dim_mid',
      'gls.dim_max',
      'gls.wblur_0',
      'gls.wblur_15',
      'gls.wblur_30',
      'gls.gblur_0',
      'gls.gblur_24',
      'gls.gblur_40',
      'gls.op_30',
      'gls.op_72',
      'gls.op_95',
      'mgmt.preview_ratio',
      'upx.policy_on',
    ]) {
      expect(MW).toContain(`data-i18n="${k}"`);
    }
    expect(MW).not.toMatch(/High Sheer|Ultra-Deep|16:9 PREVIEW|>ACTIVE<|>ONLINE</);
  });

  it('the UPS state in words, in the reader\x27s language', async () => {
    expect(upsStateWord({ available: true, on_battery: false, status: 'ONLINE' })).toBe('On mains power');
    expect(upsStateWord({ available: true, on_battery: true })).toBe('On battery');
    expect(upsStateWord({ available: false })).toBe('Offline');
    expect(upsStateWord(null)).toBe('Offline');
    expect(upsStateWord({ available: true }, true)).toBe('Permission Required');
    await setLanguage('de');
    expect(upsStateWord({ available: true, on_battery: true })).toBe('Im Akkubetrieb');
  });
});
