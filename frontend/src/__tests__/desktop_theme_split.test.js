// The themes moved out of the telemetry dashboard (first-load headroom, 18 Nov): they still apply at
// start-up, bring the wallpaper back after the Yak theme, and colour the desktop from an own accent.
import { describe, it, expect, afterEach } from 'vitest';
import { applyDesktopTheme, hexToRgb } from '../components/desktop-theme.js';
import * as dashboard from '../components/dashboard.js';

const wp = () => document.getElementById('desktop-wallpaper');

describe('desktop themes, split from the dashboard', () => {
  afterEach(() => {
    try {
      localStorage.clear();
    } catch {
      /* no storage */
    }
    document.body.innerHTML = '';
    document.documentElement.removeAttribute('style');
  });

  it('the dashboard still offers the same functions to its callers', () => {
    expect(dashboard.applyDesktopTheme).toBe(applyDesktopTheme);
    expect(dashboard.hexToRgb).toBe(hexToRgb);
    expect(hexToRgb('#369')).toEqual({ r: 51, g: 102, b: 153 });
    expect(hexToRgb('nope')).toBeNull();
  });

  it('the wallpaper comes back after the Yak theme', () => {
    document.body.innerHTML = '<div id="desktop-wallpaper"></div>';
    wp().style.backgroundImage = 'url("a.jpg")';
    applyDesktopTheme('yak');
    applyDesktopTheme('lagoon');
    expect(wp().style.backgroundImage).toContain('a.jpg');
  });

  it('a Yak wallpaper left behind becomes the saved one, or none', () => {
    document.body.innerHTML = '<div id="desktop-wallpaper"></div>';
    localStorage.setItem('kiboto_active_wallpaper', 'sunset.jpg');
    wp().style.backgroundImage = 'url("/img/yak.webp")';
    applyDesktopTheme('lagoon');
    expect(wp().style.backgroundImage).toContain('/api/wallpapers/download/sunset.jpg');
    localStorage.removeItem('kiboto_active_wallpaper');
    wp().style.backgroundImage = 'url("/img/yak.webp")';
    applyDesktopTheme('fjord');
    expect(wp().style.backgroundImage).toBe('');
  });

  it('an own accent colours the desktop', () => {
    document.body.innerHTML = '<div id="desktop-wallpaper"></div>';
    applyDesktopTheme('lagoon', '#336699');
    const styles = (document.documentElement.getAttribute('style') || '') + (document.body.getAttribute('style') || '');
    expect(styles).toContain('51, 102, 153');
  });
});
