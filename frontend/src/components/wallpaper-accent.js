// "Match my wallpaper" (APP-D): the accent is the wallpaper's strongest readable colour, taken
// again whenever the wallpaper changes. Loaded only when that switch is on or the colours are
// sampled by hand (the Look tab), never with the first page.
import { applyDesktopTheme } from './desktop-theme.js';
import { loadLook, normalizeLook, saveLookToAccount, storeLook } from '../look.js';

/** The wallpaper shown now: the desktop layer's image, else the one saved in this browser. */
export function currentWallpaperUrl(doc = typeof document === 'undefined' ? null : document) {
  const layer = doc?.getElementById('desktop-wallpaper');
  const match = layer?.style.backgroundImage?.match(/url\(["']?([^"']+)["']?\)/);
  if (match) return match[1];
  try {
    const saved = localStorage.getItem('kiboto_active_wallpaper');
    return saved ? `/api/wallpapers/download/${encodeURIComponent(saved)}` : '';
  } catch {
    return '';
  }
}

/**
 * The colours in pixels (RGBA bytes), most frequent first: quantised, without the darkest,
 * lightest and greyest ones, so each reads as an accent. Up to six.
 * @param {Uint8ClampedArray | number[]} data
 */
export function coloursOf(data) {
  const counts = new Map();
  for (let i = 0; i + 3 < data.length; i += 16) {
    if (data[i + 3] < 128) continue;
    const [r, g, b] = [data[i], data[i + 1], data[i + 2]].map((x) => Math.min(255, Math.round(x / 32) * 32));
    const top = Math.max(r, g, b);
    const sat = top === 0 ? 0 : (top - Math.min(r, g, b)) / top;
    const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    if (lum < 0.15 || lum > 0.85 || sat < 0.2) continue;
    const hex = '#' + [r, g, b].map((x) => x.toString(16).padStart(2, '0')).join('');
    counts.set(hex, (counts.get(hex) || 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([hex]) => hex);
}

/** The wallpaper's colours (coloursOf), read from a small copy of the image; [] when it cannot be read. */
export async function wallpaperColours(url, doc = typeof document === 'undefined' ? null : document) {
  if (!url || !doc) return [];
  const img = new Image();
  img.crossOrigin = 'Anonymous';
  img.src = url;
  await new Promise((resolve) => {
    img.onload = resolve;
    img.onerror = resolve;
    setTimeout(resolve, 2500);
  });
  if (!img.naturalWidth) return [];
  const canvas = doc.createElement('canvas');
  canvas.width = canvas.height = 64;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return [];
  ctx.drawImage(img, 0, 0, 64, 64);
  return coloursOf(ctx.getImageData(0, 0, 64, 64).data);
}

/** With "Match my wallpaper" on: the wallpaper's first colour becomes the accent, on every device. */
export async function followWallpaper(url = currentWallpaperUrl(), read = wallpaperColours) {
  const look = loadLook();
  if (!look.wallpaperAccent || !url) return '';
  const [hex] = await read(url);
  if (!hex || hex === look.accent) return hex || '';
  const next = normalizeLook({ ...look, accent: hex });
  storeLook(next);
  applyDesktopTheme(next.theme, hex);
  saveLookToAccount(next);
  return hex;
}
