import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../api.js', () => ({
  api: { put: vi.fn(() => Promise.resolve({ ok: true })), get: vi.fn(() => Promise.reject(new Error('signed out'))) },
}));
vi.mock('../components/desktop-theme.js', () => ({ applyDesktopTheme: vi.fn() }));
import { api } from '../api.js';
import { applyDesktopTheme } from '../components/desktop-theme.js';
import {
  applyLook,
  bindSigninLook,
  lookFor,
  nextSunChange,
  nightBySun,
  normalizeLook,
  personKey,
  rememberLookFor,
  saveLookToAccount,
  setLookOwner,
  storeLook,
  _resetForTests,
} from '../look.js';
import { coloursOf, followWallpaper } from '../components/wallpaper-accent.js';

function memoryStorage() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), _m: m };
}
const DAY = {
  days: [
    { sunrise: 1000, sunset: 2000, polar: '' },
    { sunrise: 87400, sunset: 88400, polar: '' },
  ],
};
const winDark = { matchMedia: () => ({ matches: true, addEventListener() {} }) };

beforeEach(() => {
  _resetForTests();
  localStorage.clear();
  document.body.className = '';
  vi.clearAllMocks();
});
afterEach(() => vi.useRealTimers());

describe('By sunset (APP-D)', () => {
  it('is light between sunrise and sunset and knows the next change', () => {
    expect(nightBySun(DAY, 500_000)).toBe(true);
    expect(nightBySun(DAY, 1_500_000)).toBe(false);
    expect(nightBySun(DAY, 2_500_000)).toBe(true);
    expect(nightBySun({ days: [{ polar: 'day' }] })).toBe(false);
    expect(nightBySun({ days: [{ polar: 'night' }] })).toBe(true);
    expect(nightBySun(null)).toBe(null);
    expect(nextSunChange(DAY, 1_500_000)).toBe(2_000_000);
    expect(nextSunChange(DAY, 2_500_000)).toBe(87_400_000);
    expect(nextSunChange(DAY, 99_000_000)).toBe(null);
  });

  it('is a mode of its own that follows the device until the times are known', async () => {
    expect(normalizeLook({ mode: 'sun' }).mode).toBe('sun');
    api.get.mockResolvedValueOnce({ known: true, days: [{ sunrise: 0, sunset: 1, polar: '' }] });
    expect(applyLook({ mode: 'sun' }, document, winDark)).toBe('dark'); // not known yet: the device says dark
    expect(api.get).toHaveBeenCalledWith('/api/system/sun');
    await Promise.resolve();
    await Promise.resolve();
    expect(document.body.classList.contains('theme-light')).toBe(false); // after sunset: dark
  });
});

describe('the sign-in screen in the look of the person signing in (APP-D)', () => {
  it('keeps each person’s look under a hash of their name, the last eight', () => {
    const s = memoryStorage();
    rememberLookFor('Anna', { theme: 'moss', mode: 'light' }, s);
    expect(lookFor('anna ', s)).toMatchObject({ theme: 'moss', mode: 'light' });
    expect(s._m.get('kiboto_looks_by_person')).not.toContain('Anna');
    expect(personKey('Anna')).toBe(personKey('anna'));
    for (let i = 0; i < 9; i++) rememberLookFor(`p${i}`, { theme: 'fjord' }, s);
    expect(lookFor('Anna', s)).toBe(null);
    expect(lookFor('nobody', s)).toBe(null);
    rememberLookFor('', { theme: 'fjord' }, s); // nobody signed in: nothing kept
  });

  it('a look changed while signed in is kept for that person', () => {
    setLookOwner('ben');
    saveLookToAccount({ theme: 'canyon' }, 0);
    expect(lookFor('ben')).toMatchObject({ theme: 'canyon' });
  });

  it('typing a name that signed in here shows that person’s look', () => {
    vi.useFakeTimers();
    rememberLookFor('anna', { theme: 'heather', mode: 'light' });
    storeLook({ theme: 'lagoon', mode: 'dark' });
    const input = document.createElement('input');
    bindSigninLook(input, document, winDark);
    bindSigninLook(input, document, winDark); // once
    input.value = 'Anna';
    input.dispatchEvent(new Event('input'));
    vi.advanceTimersByTime(300);
    expect(document.body.classList.contains('kb-theme-heather')).toBe(true);
    expect(document.body.classList.contains('theme-light')).toBe(true);
    input.value = 'someone else';
    input.dispatchEvent(new Event('change'));
    expect(document.body.classList.contains('kb-theme-lagoon')).toBe(true); // this browser's own look
  });
});

describe('Match my wallpaper (APP-D)', () => {
  it('takes the strongest readable colours, most frequent first', () => {
    const px = [];
    const put = (rgb, n) => {
      for (let i = 0; i < n; i++) px.push(...rgb, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    };
    put([200, 60, 40], 5); // terracotta
    put([40, 120, 200], 3); // blue
    put([128, 128, 128], 9); // grey: no accent
    put([5, 5, 5], 9); // too dark
    expect(coloursOf(px)).toEqual(['#c04020', '#2080c0']);
  });

  it('with the switch on, the wallpaper’s first colour becomes the accent', async () => {
    storeLook({ theme: 'fjord', wallpaperAccent: true });
    expect(await followWallpaper('/w.jpg', async () => ['#c04040'])).toBe('#c04040');
    expect(applyDesktopTheme).toHaveBeenCalledWith('fjord', '#c04040');
    expect(JSON.parse(localStorage.getItem('kiboto_look'))).toMatchObject({ accent: '#c04040', wallpaperAccent: true });
    applyDesktopTheme.mockClear();
    expect(await followWallpaper('/w.jpg', async () => ['#c04040'])).toBe('#c04040'); // the same: nothing redone
    expect(applyDesktopTheme).not.toHaveBeenCalled();
    storeLook({ theme: 'fjord', wallpaperAccent: false });
    expect(await followWallpaper('/w.jpg', async () => ['#00ff00'])).toBe(''); // switched off: left alone
    expect(normalizeLook({ wallpaperAccent: 'yes' }).wallpaperAccent).toBe(false);
  });
});
