/**
 * The person's look (APP-B): mode (dark, light or auto), one of five themes, the tint (0 = Subtle
 * … 1 = Strong), True black (dark mode only) and an optional own accent. It is kept with the
 * person's account, so it follows them to every device, and in this browser for a fast start.
 * Choices saved before APP-B (desktop_theme: cyber, sapphire, light, oled, …) are read and
 * translated, never overwritten, so an older cached page keeps working.
 */
import { api } from './api.js';

export const THEMES = ['lagoon', 'fjord', 'moss', 'heather', 'canyon'];
// sun (APP-D): light from sunrise to sunset where the NAS is, dark after
export const MODES = ['dark', 'light', 'auto', 'sun'];
/** @typedef {{ mode: string, theme: string, tint: number, trueBlack: boolean, accent: string, wallpaperAccent: boolean }} Look */

/** @type {Readonly<Look>} */
export const DEFAULT_LOOK = Object.freeze({
  mode: 'dark',
  theme: 'lagoon',
  tint: 0,
  trueBlack: false,
  accent: '',
  wallpaperAccent: false, // APP-D: the accent follows the wallpaper
});
/** How far the slider raises each theme's neutral colour (scripts/themes.py: TINT_MAX). */
const TINT_MAX = { lagoon: 3, fjord: 3, moss: 3, heather: 3, canyon: 2 };
/** The page colour per theme, for the phone's status bar (theme-color). */
const PAGE = {
  lagoon: ['#0a1113', '#f3f6f6'],
  fjord: ['#0b1016', '#f2f6fa'],
  moss: ['#0c110d', '#f2f7f3'],
  heather: ['#100e15', '#f6f4f9'],
  canyon: ['#130f09', '#fcf4ec'],
};
/** Each theme's main colour, dark and light (scripts/theme_palettes.json: primary). */
const PRIMARY = {
  lagoon: ['#33cdb8', '#0a7a70'],
  fjord: ['#64bdf8', '#0971a5'],
  moss: ['#98c275', '#52762f'],
  heather: ['#c69ef4', '#7a55a1'],
  canyon: ['#f39a66', '#9d522c'],
};
/** The colour a look's controls are drawn in: the person's own accent, else the theme's main colour. */
export function lookColour(look, dark = true) {
  const l = normalizeLook(look);
  return l.accent || PRIMARY[l.theme][dark ? 0 : 1];
}
/** Theme names saved before APP-B, and what they are now (scripts/theme_palettes.json: migration). */
const LEGACY = {
  cyber: { theme: 'lagoon' },
  amber: { theme: 'canyon' },
  crimson: { theme: 'canyon' },
  emerald: { theme: 'moss' },
  sapphire: { theme: 'fjord' },
  amethyst: { theme: 'heather' },
  light: { theme: 'lagoon', mode: 'light' },
  oled: { theme: 'lagoon', mode: 'dark', trueBlack: true },
  auto: { theme: 'lagoon', mode: 'auto' },
  system: { theme: 'lagoon', mode: 'auto' },
};
const LOOK_KEY = 'kiboto_look';
// a theme's stylesheet loads when it is chosen, not with the first page (first-load budget)
const SHEETS = {
  lagoon: () => import('./styles/themes/lagoon.css'),
  fjord: () => import('./styles/themes/fjord.css'),
  moss: () => import('./styles/themes/moss.css'),
  heather: () => import('./styles/themes/heather.css'),
  canyon: () => import('./styles/themes/canyon.css'),
};

/**
 * A look with every field present and valid; anything unknown falls back to the default.
 * @param {any} raw
 * @returns {Look}
 */
export function normalizeLook(raw) {
  const r = raw && typeof raw === 'object' ? raw : {};
  const tint = Number(r.tint);
  const accent = typeof r.accent === 'string' && /^#[0-9a-f]{6}$/i.test(r.accent) ? r.accent.toLowerCase() : '';
  return {
    mode: MODES.includes(r.mode) ? r.mode : DEFAULT_LOOK.mode,
    theme: THEMES.includes(r.theme) ? r.theme : DEFAULT_LOOK.theme,
    tint: Number.isFinite(tint) ? Math.min(1, Math.max(0, Math.round(tint * 100) / 100)) : 0,
    trueBlack: r.trueBlack === true,
    accent,
    wallpaperAccent: r.wallpaperAccent === true,
  };
}

/**
 * A theme name saved before APP-B as a look (unknown names give the default).
 * @param {string} name
 * @param {Look} [base]
 * @returns {Look}
 */
export function fromLegacy(name, base = DEFAULT_LOOK) {
  return normalizeLook({ ...base, ...(LEGACY[name] || (THEMES.includes(name) ? { theme: name } : {})) });
}

function _storage() {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

/** Whether this browser holds a look saved since APP-B. */
export function hasOwnLook(storage = _storage()) {
  try {
    return Boolean(storage && storage.getItem(LOOK_KEY));
  } catch {
    return false;
  }
}

/** This browser's look: the saved one, else the pre-APP-B theme (and accent), else the default. */
export function loadLook(storage = _storage()) {
  try {
    const saved = storage && storage.getItem(LOOK_KEY);
    if (saved) return normalizeLook(JSON.parse(saved));
    const legacy = storage && storage.getItem('desktop_theme');
    const accent = (storage && storage.getItem('desktop_custom_accent')) || '';
    // a saved "yak" (a hidden theme, removed) becomes the default look
    return normalizeLook({ ...fromLegacy(legacy && legacy !== 'yak' ? legacy : 'cyber'), accent });
  } catch {
    return { ...DEFAULT_LOOK };
  }
}

/** Keeps the look in this browser (the old desktop_theme key is left alone). */
export function storeLook(look, storage = _storage()) {
  try {
    storage?.setItem(LOOK_KEY, JSON.stringify(normalizeLook(look)));
  } catch {}
}

/** How strongly the neutrals are tinted: 1 at Subtle, up to the theme's maximum at Strong. */
export function tintFactor(look) {
  const l = normalizeLook(look);
  return Math.round((1 + l.tint * (TINT_MAX[l.theme] - 1)) * 100) / 100;
}

let _darkQuery = null;
let _applied = null;
let _sun = null; // GET /api/system/sun, with when it was asked
let _sunTimer = null;

/** Whether it is night where the NAS is ("By sunset"); null while that is not known. */
export function nightBySun(sun, nowMs = Date.now()) {
  const day = sun?.days?.[0];
  if (!day) return null;
  if (day.polar) return day.polar === 'night';
  const now = nowMs / 1000;
  return now < day.sunrise || now >= day.sunset;
}

/** The next sunrise or sunset after now, in milliseconds, or null. */
export function nextSunChange(sun, nowMs = Date.now()) {
  for (const day of sun?.days || []) {
    for (const at of [day.sunrise, day.sunset]) if (at && at * 1000 > nowMs) return at * 1000;
  }
  return null;
}

/** Asks for today's sunrise and sunset (once, and again after midnight) and switches at each. */
function _followSun(win) {
  const fresh = _sun && Date.now() - _sun.at < 12 * 3600 * 1000;
  if (fresh || _sun?.asking) return;
  _sun = { ...(_sun || {}), asking: true, at: _sun?.at || 0 };
  api
    .get('/api/system/sun')
    .then((answer) => {
      _sun = { ...answer, at: Date.now() };
      if (_applied?.look.mode === 'sun') applyLook(_applied.look, _applied.doc, win);
    })
    .catch(() => {
      _sun = null; // the sign-in screen: the device's own preference until someone signs in
    });
}

function _scheduleSun(win) {
  clearTimeout(_sunTimer);
  const next = nextSunChange(_sun);
  const wait = next ? next - Date.now() + 5000 : 6 * 3600 * 1000;
  _sunTimer = setTimeout(
    () => {
      if (!next && _sun) _sun.at = 0; // after the last known change: ask again
      if (_applied?.look.mode === 'sun') applyLook(_applied.look, _applied.doc, win);
    },
    Math.min(wait, 2 ** 31 - 1)
  );
}

function _prefersDark(win) {
  if (!win?.matchMedia) return true;
  if (!_darkQuery) {
    _darkQuery = win.matchMedia('(prefers-color-scheme: dark)');
    // Auto follows the device while the page is open
    _darkQuery.addEventListener?.('change', () => {
      if (_applied && _applied.look.mode === 'auto') applyLook(_applied.look, _applied.doc, win);
    });
  }
  return _darkQuery.matches;
}

/**
 * Puts the look on the page: the theme's class, light or dark, True black, the tint, the phone's
 * status-bar colour, and the theme's stylesheet when it is needed. Returns "dark" or "light".
 */
export function applyLook(
  look,
  doc = typeof document === 'undefined' ? null : document,
  win = typeof window === 'undefined' ? null : window
) {
  const l = normalizeLook(look);
  let night = null;
  if (l.mode === 'sun') {
    _followSun(win);
    night = nightBySun(_sun);
    _scheduleSun(win);
  }
  const dark =
    l.mode === 'dark' ||
    night === true ||
    ((l.mode === 'auto' || (l.mode === 'sun' && night === null)) && _prefersDark(win));
  _applied = { look: l, doc };
  const body = doc?.body;
  if (body) {
    for (const c of [...body.classList]) if (c.startsWith('kb-theme-')) body.classList.remove(c);
    body.classList.add(`kb-theme-${l.theme}`);
    body.classList.toggle('theme-light', !dark);
    body.classList.toggle('theme-oled', dark && l.trueBlack);
    body.classList.toggle('kb-tinted', l.tint > 0);
    if (l.tint > 0) body.style.setProperty('--kb-tint', String(tintFactor(l)));
    else body.style.removeProperty('--kb-tint');
    if (l.theme !== 'lagoon' || l.tint > 0) SHEETS[l.theme]().catch(() => null);
  }
  const meta = doc?.querySelector?.('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', PAGE[l.theme][dark ? 0 : 1]);
  return dark ? 'dark' : 'light';
}

/** Takes the look classes off the page. */
export function clearLook(doc = typeof document === 'undefined' ? null : document) {
  const body = doc?.body;
  if (!body) return;
  for (const c of [...body.classList]) if (c.startsWith('kb-theme-')) body.classList.remove(c);
  body.classList.remove('kb-tinted', 'theme-light', 'theme-oled');
  body.style.removeProperty('--kb-tint');
}

// The sign-in screen in the look of the person signing in (APP-D): each person's look is kept in
// this browser, under a hash of their name, when they sign in or change it; nothing is asked of the
// server, so the screen tells nobody which names have accounts.
const PEOPLE_KEY = 'kiboto_looks_by_person';
const PEOPLE_KEPT = 8;
let _owner = '';

/** A short hash of a name (FNV-1a), so the browser does not list who signed in on it. */
export function personKey(name) {
  let h = 0x811c9dc5;
  for (const ch of String(name || '')
    .trim()
    .toLowerCase()) {
    h ^= ch.codePointAt(0) || 0;
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16);
}

/** Keeps a person's look in this browser (the last eight people). */
export function rememberLookFor(name, look, storage = _storage()) {
  if (!name) return;
  try {
    const all = JSON.parse(storage?.getItem(PEOPLE_KEY) || '{}');
    const key = personKey(name);
    delete all[key];
    all[key] = normalizeLook(look);
    const keys = Object.keys(all);
    for (const old of keys.slice(0, Math.max(0, keys.length - PEOPLE_KEPT))) delete all[old];
    storage?.setItem(PEOPLE_KEY, JSON.stringify(all));
  } catch {}
}

/** The look this browser keeps for a name, or null. */
export function lookFor(name, storage = _storage()) {
  try {
    const found = JSON.parse(storage?.getItem(PEOPLE_KEY) || '{}')[personKey(name)];
    return found ? normalizeLook(found) : null;
  } catch {
    return null;
  }
}

/** Who is signed in: their look changes are kept for the sign-in screen too. */
export function setLookOwner(name) {
  _owner = String(name || '');
}

/** The sign-in screen takes the look of a name that signed in here before, as it is typed. */
export function bindSigninLook(
  input,
  doc = typeof document === 'undefined' ? null : document,
  win = typeof window === 'undefined' ? null : window
) {
  if (!input || input.dataset.lookBound) return;
  input.dataset.lookBound = '1';
  let timer = null;
  const show = () => {
    applyLook(lookFor(input.value) || loadLook(), doc, win);
  };
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(show, 250);
  });
  input.addEventListener('change', show);
}

let _saveTimer = null;
/** Saves the look on the person's account (a moment later, once the slider stops). Never throws. */
export function saveLookToAccount(look, delay = 400) {
  rememberLookFor(_owner, look);
  clearTimeout(_saveTimer);
  return new Promise((resolve) => {
    _saveTimer = setTimeout(() => {
      api.put('/api/auth/me/preferences', { look: normalizeLook(look) }).then(resolve, () => resolve(null));
    }, delay);
  });
}

/** The look saved on the person's account, or null when they have none yet. */
export function lookFromAccount(user) {
  const look = user?.preferences?.look;
  return look && typeof look === 'object' ? normalizeLook(look) : null;
}

export function _resetForTests() {
  _darkQuery = null;
  _applied = null;
  _sun = null;
  _owner = '';
  clearTimeout(_sunTimer);
  clearTimeout(_saveTimer);
}
