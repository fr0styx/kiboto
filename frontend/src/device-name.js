// A signed-in device by its browser and system ("Chrome on Windows") instead of the raw
// User-Agent line; the same reading as backend/services/known_devices.py (re-audit R1).
import { t } from './i18n.js';

// Edge, Opera and Samsung's browser also say "Chrome"; Chrome also says "Safari"
const BROWSERS = [
  ['Edg', 'Edge'],
  ['OPR/', 'Opera'],
  ['SamsungBrowser/', 'Samsung Internet'],
  ['FxiOS/', 'Firefox'],
  ['Firefox/', 'Firefox'],
  ['CriOS/', 'Chrome'],
  ['Chrome/', 'Chrome'],
  ['Safari/', 'Safari'],
];
const SYSTEMS = [
  ['iPhone', 'iPhone'],
  ['iPad', 'iPad'],
  ['Android', 'Android'],
  ['Windows', 'Windows'],
  ['Macintosh', 'Mac'],
  ['CrOS', 'ChromeOS'],
  ['Linux', 'Linux'],
];

/** "Chrome on Windows" for a User-Agent; the line itself when it names neither; '' when empty. */
export function deviceName(userAgent) {
  const ua = String(userAgent || '');
  const system = (SYSTEMS.find(([mark]) => ua.includes(mark)) || [])[1] || '';
  const browser = (BROWSERS.find(([mark]) => ua.includes(mark)) || [])[1] || '';
  if (browser && system) return t('device.on', '{browser} on {system}', { browser, system });
  return browser || system || ua;
}
