// Re-audit R1: device lists name the browser and the system, and History says "a new device".
import { describe, it, expect, afterEach } from 'vitest';
import { deviceName } from '../device-name.js';
import { signinSentence } from '../components/history-signins.js';
import { devicesHtml } from '../components/person-page.js';
import { setLanguage } from '../i18n.js';

const CHROME_WIN =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
const SAFARI_IPHONE =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.0 Mobile/15E148 Safari/604.1';

describe('device names', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('names the browser and the system', () => {
    expect(deviceName(CHROME_WIN)).toBe('Chrome on Windows');
    expect(deviceName(SAFARI_IPHONE)).toBe('Safari on iPhone');
    expect(deviceName(CHROME_WIN + ' Edg/141.0.0.0')).toBe('Edge on Windows');
    expect(deviceName('Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0')).toBe(
      'Firefox on Linux'
    );
  });

  it('keeps what it cannot read, and says nothing for nothing', () => {
    expect(deviceName('curl/8.5.0')).toBe('curl/8.5.0');
    expect(deviceName('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')).toBe('Mac');
    expect(deviceName('')).toBe('');
    expect(deviceName(undefined)).toBe('');
  });

  it('is written in the reader language', async () => {
    await setLanguage('de');
    expect(deviceName(CHROME_WIN)).toBe('Chrome unter Windows');
  });

  it('the device list shows the name, not the raw line', () => {
    const html = devicesHtml([{ user_agent: SAFARI_IPHONE, ip_address: '192.168.1.30', last_active_at: 0 }]);
    expect(html).toContain('Safari on iPhone');
    expect(html).not.toContain('AppleWebKit');
    expect(devicesHtml([{ user_agent: '' }])).toContain('Unknown browser');
  });

  it('History says who signed in from which new device', () => {
    expect(
      signinSentence({
        event_type: 'auth.login.new_device',
        actor_username: 'mara',
        details: { device: 'Safari on iPhone' },
      })
    ).toBe('mara signed in from a new device: Safari on iPhone');
    expect(signinSentence({ event_type: 'auth.login.new_device', actor_username: 'mara' })).toContain('?');
  });
});
