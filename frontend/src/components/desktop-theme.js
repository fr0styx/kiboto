/**
 * The desktop's and the front screen's themes (split out of dashboard.js, 18 Nov 2026): these run at
 * start-up, before any stats; the telemetry dashboard itself loads when it is first needed, which
 * keeps about 20 kB out of the first load.
 */
import { state } from '../state.js';
import { ZettEventBus } from '../event-bus.js';
import { t } from '../i18n.js';
import {
  applyLook,
  clearLook,
  fromLegacy,
  loadLook,
  lookColour,
  lookFromAccount,
  normalizeLook,
  storeLook,
} from '../look.js';

const $ = (id) => document.getElementById(id);
// the drive trays are drawn by the dashboard: asked for when it is there, never loaded for this
const updateChassisImageForTheme = () =>
  import('./dashboard.js').then((m) => m.updateChassisImageForTheme()).catch(() => {});

function _restoreNonYakWallpaper(wpLayer) {
  if (!wpLayer) return;
  if (wpLayer.dataset.previousWallpaper) {
    wpLayer.style.setProperty('background-image', wpLayer.dataset.previousWallpaper);
    delete wpLayer.dataset.previousWallpaper;
  } else if (wpLayer.style.backgroundImage && wpLayer.style.backgroundImage.includes('yak.webp')) {
    const savedWp = typeof localStorage !== 'undefined' ? localStorage.getItem('kiboto_active_wallpaper') : null;
    if (savedWp) {
      const wpUrl =
        savedWp.startsWith('/') || savedWp.startsWith('http')
          ? savedWp
          : `/api/wallpapers/download/${encodeURIComponent(savedWp)}`;
      wpLayer.style.setProperty('background-image', `url('${wpUrl}')`);
    } else {
      wpLayer.style.removeProperty('background-image');
    }
  }
  wpLayer.style.removeProperty('background-size');
  wpLayer.style.removeProperty('background-position');
  wpLayer.style.removeProperty('background-repeat');
  wpLayer.style.removeProperty('background-color');
}

/**
 * The desktop's look (APP-B). themeName is one of the five themes (lagoon, fjord, moss, heather,
 * canyon), a name saved before APP-B (cyber, sapphire, light, oled, auto, …: translated, keeping
 * the rest of the look), or "yak", the hidden theme. customAccent: a colour, '' for the theme's
 * own, or null to keep the current one.
 */
export function applyDesktopTheme(themeName, customAccent = null) {
  const current = loadLook();
  const look =
    themeName === 'yak'
      ? current
      : normalizeLook({
          ...fromLegacy(themeName, current),
          accent: customAccent === undefined || customAccent === null ? current.accent : customAccent,
        });
  customAccent = look.accent;
  if (themeName !== 'yak') storeLook(look);

  state.setDesktopTheme(themeName === 'yak' ? 'yak' : look.theme, customAccent);

  if (typeof document !== 'undefined' && document.body) {
    const wpLayer = document.getElementById('desktop-wallpaper');

    if (themeName === 'yak') {
      clearLook(document);
      // the hidden Yak theme loads only when it is chosen (first-load budget)
      import('../styles/04-yak-theme.css').catch(() => null);
      document.body.classList.add('theme-yak');
      if (wpLayer) {
        if (
          !wpLayer.dataset.previousWallpaper &&
          wpLayer.style.backgroundImage &&
          !wpLayer.style.backgroundImage.includes('yak.webp')
        ) {
          wpLayer.dataset.previousWallpaper = wpLayer.style.backgroundImage;
        }
        wpLayer.style.setProperty('background-image', 'url("/img/yak.webp")', 'important');
        wpLayer.style.setProperty('background-size', 'contain', 'important');
        wpLayer.style.setProperty('background-position', 'center center', 'important');
        wpLayer.style.setProperty('background-repeat', 'no-repeat', 'important');
        wpLayer.style.setProperty('background-color', '#060b09', 'important');
        wpLayer.style.display = 'block';
      }
    } else {
      applyLook(look, document);
      if (wpLayer) _restoreNonYakWallpaper(wpLayer);
    }
  }

  // Helper to parse hex to RGB with strict sanitization
  const hexToRgb = (hex) => {
    if (!hex || typeof hex !== 'string') return null;
    let clean = hex.replace('#', '').trim();
    if (!/^[0-9a-fA-F]{3}$|^[0-9a-fA-F]{6}$/.test(clean)) return null;
    if (clean.length === 3)
      clean = clean
        .split('')
        .map((c) => c + c)
        .join('');
    const num = parseInt(clean, 16);
    if (isNaN(num)) return null;
    return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
  };

  const srgbToLinear = (c) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };

  const getRelativeLuminance = (r, g, b) => {
    return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
  };

  // Handle custom accent color override for desktop UI
  if (customAccent) {
    const rgb = hexToRgb(customAccent);
    const rgbStr = rgb ? `${rgb.r}, ${rgb.g}, ${rgb.b}` : null;
    const glowStr = rgb ? `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.35)` : '';
    const hoverStr = rgb ? `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.15)` : '';
    const lum = rgb ? getRelativeLuminance(rgb.r, rgb.g, rgb.b) : 0.5;
    const contrastFg = lum > 0.45 ? '#0c1517' : '#ffffff';

    if (typeof document !== 'undefined' && document.documentElement) {
      document.documentElement.style.setProperty('--brand', customAccent);
      document.documentElement.style.setProperty('--ok2', customAccent);
      document.documentElement.style.setProperty('--desktop-accent', customAccent);
      document.documentElement.style.setProperty('--accent-contrast-fg', contrastFg);
      if (rgbStr) {
        document.documentElement.style.setProperty('--brand-rgb', rgbStr);
        document.documentElement.style.setProperty('--accent-rgb', rgbStr);
        document.documentElement.style.setProperty('--accent-glow', glowStr);
        document.documentElement.style.setProperty('--accent-hover', hoverStr);
      }
    }
    if (typeof document !== 'undefined' && document.body) {
      document.body.style.setProperty('--brand', customAccent);
      document.body.style.setProperty('--ok2', customAccent);
      document.body.style.setProperty('--desktop-accent', customAccent);
      document.body.style.setProperty('--accent-contrast-fg', contrastFg);
      if (rgbStr) {
        document.body.style.setProperty('--brand-rgb', rgbStr);
        document.body.style.setProperty('--accent-rgb', rgbStr);
        document.body.style.setProperty('--accent-glow', glowStr);
        document.body.style.setProperty('--accent-hover', hoverStr);
      }
    }
  } else {
    if (typeof document !== 'undefined' && document.documentElement) {
      document.documentElement.style.removeProperty('--brand');
      document.documentElement.style.removeProperty('--ok2');
      document.documentElement.style.removeProperty('--desktop-accent');
      document.documentElement.style.removeProperty('--accent-contrast-fg');
      document.documentElement.style.removeProperty('--brand-rgb');
      document.documentElement.style.removeProperty('--accent-rgb');
      document.documentElement.style.removeProperty('--accent-glow');
      document.documentElement.style.removeProperty('--accent-hover');
    }
    if (typeof document !== 'undefined' && document.body) {
      document.body.style.removeProperty('--brand');
      document.body.style.removeProperty('--ok2');
      document.body.style.removeProperty('--desktop-accent');
      document.body.style.removeProperty('--accent-contrast-fg');
      document.body.style.removeProperty('--brand-rgb');
      document.body.style.removeProperty('--accent-rgb');
      document.body.style.removeProperty('--accent-glow');
      document.body.style.removeProperty('--accent-hover');
    }
  }

  const isYak = themeName === 'yak';
  const yakEggBtn = $('yak-easter-egg-btn');
  if (yakEggBtn) {
    yakEggBtn.title = isYak
      ? 'Yak Express Active! [Press Y or click to toggle]'
      : 'Trust in the Yak [Easter Egg Hot-key: Y]';
  }

  const title = $('suite-brand-title');
  const badge = $('suite-brand-badge');
  const drawerSub = $('drawer-sub-badge');
  const icon = $('suite-brand-icon');

  if (title) title.textContent = isYak ? 'YAK EXPRESS' : 'KIBOTO';
  if (badge) badge.textContent = isYak ? 'RELIABILITY CULT' : t('nav.badge', 'Beta');
  if (drawerSub) drawerSub.textContent = isYak ? 'LOGISTICS LAB' : t('settings.drawer_badge', 'Beta');
  if (icon) icon.innerHTML = isYak ? '<use href="#i-yak"/>' : '<use href="#i-chip"/>';

  updateChassisImageForTheme();
  syncDesktopTwinPreview({ theme: themeName, accent: customAccent });
}

export function syncDesktopTwinPreview(overrides = {}) {
  if (typeof document === 'undefined') return;
  const vp = document.getElementById('desktop-twin-viewport');
  if (!vp) return;

  const curTheme = overrides.theme || state.desktopTheme || 'lagoon';
  const curAccent = overrides.accent !== undefined ? overrides.accent : state.desktopCustomAccent || '';
  const activeColor =
    curTheme === 'yak' ? '#d48a37' : lookColour({ ...loadLook(), theme: curTheme, accent: curAccent });
  const rgb = hexToRgb(activeColor);

  const badge = document.getElementById('dt-theme-badge');
  if (badge) {
    badge.textContent = curTheme.toUpperCase();
    badge.style.color = `var(--lt-ink-brand, ${activeColor})`;
    badge.style.borderColor = activeColor;
    badge.style.background = rgb ? `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.15)` : 'rgba(51, 205, 184, 0.15)';
  }

  const dtWp = document.getElementById('dt-wallpaper');
  if (dtWp) {
    const desktopWp = document.getElementById('desktop-wallpaper');
    if (desktopWp && desktopWp.style.backgroundImage) {
      dtWp.style.backgroundImage = desktopWp.style.backgroundImage;
      dtWp.style.display = 'block';
    } else if (overrides.wallpaperUrl) {
      dtWp.style.backgroundImage = `url('${overrides.wallpaperUrl}')`;
      dtWp.style.display = 'block';
    } else if (overrides.wallpaperUrl === null) {
      dtWp.style.removeProperty('background-image');
    }
    if (overrides.wallpaperBlur !== undefined) {
      dtWp.style.setProperty('--preview-wp-blur', `${overrides.wallpaperBlur}px`);
    }
  }

  const dtDim = document.getElementById('dt-wallpaper-dimmer');
  if (dtDim && overrides.wallpaperDim !== undefined) {
    dtDim.style.setProperty('--preview-wp-dim', (overrides.wallpaperDim / 100).toFixed(2));
  }

  const dtWin = document.getElementById('dt-window');
  if (dtWin) {
    if (rgb) {
      dtWin.style.setProperty('--preview-accent-rgb', `${rgb.r}, ${rgb.g}, ${rgb.b}`);
    }
    if (overrides.glassBlur !== undefined) {
      dtWin.style.setProperty('--preview-glass-blur', `${overrides.glassBlur}px`);
    }
    if (overrides.glassOpacity !== undefined) {
      dtWin.style.setProperty('--preview-glass-opacity', (overrides.glassOpacity / 100).toFixed(2));
    }
    if (overrides.windowRadius !== undefined) {
      dtWin.style.setProperty('--preview-window-radius', overrides.windowRadius);
    }
    if (overrides.windowGlow !== undefined) {
      dtWin.style.setProperty('--preview-window-glow', overrides.windowGlow ? '1' : '0');
    }
  }

  const dtDockCont = document.getElementById('dt-dock-container');
  if (dtDockCont && overrides.dockPos !== undefined) {
    dtDockCont.className = `dt-dock-container dt-dock-pos-${overrides.dockPos}`;
  }
}
if (typeof window !== 'undefined') {
  window.syncDesktopTwinPreview = syncDesktopTwinPreview;
}

export function applyLcdTheme(themeName, customAccent = null, textClarity = null) {
  if (customAccent === undefined || customAccent === null) {
    customAccent =
      state.lcdCustomAccent ||
      (typeof localStorage !== 'undefined' ? localStorage.getItem('lcd_custom_accent') : '') ||
      '';
  }
  if (textClarity === undefined || textClarity === null) {
    textClarity =
      state.lcdTextClarity !== undefined
        ? state.lcdTextClarity
        : typeof localStorage !== 'undefined'
          ? localStorage.getItem('lcd_text_clarity') !== 'false'
          : true;
  }

  state.setLcdTheme(themeName, customAccent, textClarity);

  const targets = [];
  const screenEl = $('screen');
  const miniCanvas = $('mini-lcd-canvas');
  const consoleWin = $('console-window');
  if (screenEl) targets.push(screenEl);
  if (miniCanvas) targets.push(miniCanvas);
  if (consoleWin) targets.push(consoleWin);

  // If running directly on the physical display, also apply to document.body
  if (state.isLcdDirect && typeof document !== 'undefined' && document.body) {
    targets.push(document.body);
  }

  const allLcdThemes = [
    'lcd-theme-cyber',
    'lcd-theme-amber',
    'lcd-theme-emerald',
    'lcd-theme-sapphire',
    'lcd-theme-amethyst',
    'lcd-theme-crimson',
    'lcd-theme-light',
    'lcd-theme-yak',
  ];

  targets.forEach((el) => {
    el.classList.remove(...allLcdThemes);
    if (themeName && themeName !== 'cyber') {
      el.classList.add(`lcd-theme-${themeName}`);
    } else {
      el.classList.add('lcd-theme-cyber');
    }

    if (customAccent) {
      el.style.setProperty('--brand', customAccent);
      el.style.setProperty('--ok2', customAccent);
      el.style.setProperty('--lcd-brand', customAccent);
      el.style.setProperty('--lcd-ok2', customAccent);
      el.style.setProperty('--lcd-accent', customAccent);
    } else {
      el.style.removeProperty('--brand');
      el.style.removeProperty('--ok2');
      el.style.removeProperty('--lcd-brand');
      el.style.removeProperty('--lcd-ok2');
      el.style.removeProperty('--lcd-accent');
    }

    el.classList.toggle('text-clarity-on', Boolean(textClarity));
    el.classList.toggle('text-clarity-off', !textClarity);
  });

  const isYak = themeName === 'yak';
  const engraved = $('chassis-panel-engraved');
  if (engraved)
    engraved.textContent = isYak
      ? 'YAK EXPRESS • TOASTIE LOGISTICS LAB'
      : t('console.engraved_title', 'KIBOTO • SYSTEM CONSOLE');

  // Update module card titles inside #screen and #mini-lcd-canvas
  document.querySelectorAll('.card-storage .card-title-txt').forEach((el) => {
    el.textContent = isYak ? 'CARGO HOLD' : t('console.storage', 'STORAGE');
  });
  document.querySelectorAll('.card-cpu .card-title-txt').forEach((el) => {
    el.textContent = isYak ? 'YAK64 CPU' : t('console.cpu', 'CPU');
  });
  document.querySelectorAll('.card-fans .card-title-txt').forEach((el) => {
    el.textContent = isYak ? 'YAK AIRFLOW' : t('console.fans', 'FANS');
  });
  document.querySelectorAll('.card-net .card-title-txt').forEach((el) => {
    el.textContent = isYak ? 'TRANSIT I/O' : t('console.net', 'NETWORK I/O');
  });

  if ($('lbl-module-storage'))
    $('lbl-module-storage').textContent = isYak
      ? 'Cargo Hold (Capacity & Donut)'
      : t('settings.mod_storage', 'Storage (Donut & Capacity)');
  if ($('lbl-module-cpu'))
    $('lbl-module-cpu').textContent = isYak ? 'YAK64 Toastie CPU' : t('settings.mod_cpu', 'CPU Gauge');
  if ($('lbl-module-fans'))
    $('lbl-module-fans').textContent = isYak ? 'Asthmatic Yak Airflow & Fans' : t('settings.mod_fans', 'Fans & Uptime');
  if ($('lbl-module-disks'))
    $('lbl-module-disks').textContent = isYak
      ? 'Yak Parcel Bays (OS, Data, Cache)'
      : t('settings.mod_disks', 'Drives Tray (OS, Data, Cache)');
  if ($('lbl-module-net'))
    $('lbl-module-net').textContent = isYak
      ? 'Transit Courier Throughput'
      : t('settings.mod_net', 'Network Throughput');

  const stageGlow = $('virtual-chassis-lightbar');
  if (stageGlow) {
    if (isYak) {
      stageGlow.style.background = 'linear-gradient(90deg, #1b68b8 0%, #e07a38 50%, #1b68b8 100%)';
      stageGlow.style.boxShadow = '0 0 16px rgba(224, 122, 56, 0.5)';
    } else {
      stageGlow.style.removeProperty('background');
      stageGlow.style.removeProperty('box-shadow');
      delete stageGlow.dataset.look;
      // what the bar shows; the light bar's code loads when there is a bar to draw
      import('./led-control.js')
        .then((m) => m.renderLightbar(stageGlow, state.latestStats?.lightbar, { offOpacity: 0.15 }))
        .catch(() => {});
    }
  }

  if (state.latestStats && state.latestStats.disks) updateChassisImageForTheme();
}

/** At sign-in: the look saved on the person's account, on this device too (APP-B). */
export function adoptAccountLook(user) {
  const look = lookFromAccount(user);
  if (!look || state.desktopTheme === 'yak') return false;
  storeLook(look);
  applyDesktopTheme(look.theme, look.accent);
  return true;
}
ZettEventBus.on?.('session:user', adoptAccountLook);

// Backward-compatible alias
export function applyTheme(themeName, customAccent = null, textClarity = null) {
  applyDesktopTheme(themeName, customAccent);
  if (textClarity !== null || state.isLcdDirect) {
    applyLcdTheme(themeName, customAccent, textClarity);
  }
}

export function hexToRgb(hex) {
  if (!hex || typeof hex !== 'string') return null;
  let clean = hex.replace('#', '').trim();
  if (!/^[0-9a-fA-F]{3}$|^[0-9a-fA-F]{6}$/.test(clean)) return null;
  if (clean.length === 3)
    clean = clean
      .split('')
      .map((c) => c + c)
      .join('');
  const num = parseInt(clean, 16);
  if (isNaN(num)) return null;
  return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
}
