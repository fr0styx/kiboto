import { describe, it, expect, vi } from 'vitest';
import fs from 'node:fs';
import { routeFromHash } from '../router.js';
import { setAppBadge, watchLaunches } from '../pwa.js';

function serviceWorker() {
  const src = fs.readFileSync('frontend/public/sw.js', 'utf8');
  const self = { addEventListener() {}, navigator: { language: 'en' }, location: { origin: 'http://x' } };
  return new Function('self', `${src}; return { offlinePage };`)(self);
}

describe('installable app polish (COMP-02)', () => {
  it('offline page speaks the browser language and tries again by itself', () => {
    const { offlinePage } = serviceWorker();
    const de = offlinePage('de-DE,de;q=0.9,en;q=0.8');
    expect(de).toContain('<html lang="de">');
    expect(de).toContain('Kiboto ist nicht erreichbar');
    expect(de).toContain("addEventListener('online'");
    expect(de).toContain('setInterval(again,5000)');
    expect(offlinePage('fr-CA')).toContain('Kiboto est injoignable');
    expect(offlinePage('pt-BR')).toContain('<html lang="en">');
    expect(offlinePage('')).toContain('Kiboto is not reachable');
  });

  it('manifest shortcuts lead to real places and relaunches reuse the open window', () => {
    const m = JSON.parse(fs.readFileSync('frontend/public/manifest.json', 'utf8'));
    expect(m.shortcuts.length).toBeGreaterThanOrEqual(3);
    for (const s of m.shortcuts) {
      expect(s.name).toBeTruthy();
      expect(routeFromHash(new URL(s.url, 'http://x').hash)).toBeTruthy();
    }
    expect(m.launch_handler.client_mode[0]).toBe('focus-existing');
  });

  it('a relaunch opens its place; the first launch is left to the router', () => {
    let consumer = null;
    const win = {
      launchQueue: { setConsumer: (fn) => (consumer = fn) },
      history: { replaceState: vi.fn() },
    };
    const open = vi.fn(() => true);
    expect(watchLaunches(win, open)).toBe(true);
    consumer({ targetURL: 'http://x/#/files' });
    expect(open).not.toHaveBeenCalled();
    consumer({ targetURL: 'http://x/#/drives' });
    expect(open).toHaveBeenCalledWith('#/drives');
    expect(win.history.replaceState).toHaveBeenCalledWith(null, '', '/#/drives');
    expect(watchLaunches({}, open)).toBe(false);
  });

  it('the icon badge shows the unread count once per change and clears at zero', () => {
    const nav = { setAppBadge: vi.fn(() => Promise.resolve()), clearAppBadge: vi.fn(() => Promise.resolve()) };
    setAppBadge(3, nav);
    setAppBadge(3, nav);
    expect(nav.setAppBadge).toHaveBeenCalledTimes(1);
    expect(nav.setAppBadge).toHaveBeenCalledWith(3);
    setAppBadge(0, nav);
    expect(nav.clearAppBadge).toHaveBeenCalledTimes(1);
    expect(() => setAppBadge(5, {})).not.toThrow();
  });
});
