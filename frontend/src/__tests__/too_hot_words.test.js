// The Overview's "too hot" names what is too hot, in the reader's language (Hardware 3).
import { describe, it, expect, afterEach } from 'vitest';
import { itemText, hotWords } from '../components/management/overview.js';
import { setLanguage } from '../i18n.js';

describe('too hot, and what', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('names the drives and the processor', () => {
    const i = { kind: 'too_hot', subject: '', hot: { drives: [{ name: 'sdb', temp: 57 }], cpu: 82 } };
    expect(itemText(i)).toBe(
      'Too hot: drive sdb at 57 °C, the processor at 82 °C. The fans run at full speed; check that nothing blocks the air around the NAS.'
    );
    expect(hotWords({ drives: [], cpu: 80 })).toBe('the processor at 80 °C');
    expect(hotWords(null)).toBe('');
  });

  it('without a part it stays the plain line', () => {
    expect(itemText({ kind: 'too_hot', subject: '' })).toBe('The server is too hot.');
  });

  it('in German', async () => {
    await setLanguage('de');
    expect(itemText({ kind: 'too_hot', hot: { drives: [{ name: 'sdb', temp: 57 }], cpu: null } })).toMatch(
      /^Zu heiß: Laufwerk sdb mit 57 °C\. /
    );
  });

  it('other messages are unchanged', () => {
    expect(itemText({ kind: 'on_battery' })).toBe('The server is running on battery power.');
  });
});
