// Why Restart or Shut down cannot work here, in the reader's language (17 Nov).
import { describe, it, expect, afterEach } from 'vitest';
import { whyNot } from '../components/management/power-switch.js';
import { setLanguage } from '../i18n.js';

describe('power: why not here', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('the key wins, then the sentence, then nothing', async () => {
    await setLanguage('de');
    expect(whyNot({ why: 'x', text: { msg_key: 'srv.power_no_host_command', params: { name: 'reboot' } } })).toContain(
      '/host/reboot'
    );
    expect(whyNot({ why: 'x', text: { msg_key: 'srv.power_no_command' } })).toContain('keinen Befehl');
    expect(whyNot({ why: 'Server words' })).toBe('Server words');
    expect(whyNot({ ok: false })).toBe('');
    expect(whyNot(null)).toBe('');
  });
});
