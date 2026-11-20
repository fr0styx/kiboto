import { describe, it, expect, vi, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

vi.mock('../api.js', () => ({
  api: {
    get: vi.fn(async () => ({
      ok: false,
      items: [{ kind: 'pool_full', level: 'warning', subject: 'tank', open: 'storage' }],
    })),
  },
}));

const { enablePhoneShell, onPhoneBack, openAlertsPage, setCompactBack } = await import('../components/phone-shell.js');
const { BREAKPOINTS } = await import('../device.js');
const tick = () => new Promise((r) => setTimeout(r, 40));
const STYLES = path.resolve(__dirname, '..', 'styles');

describe('UX-37: phones and tablets', () => {
  afterEach(() => {
    enablePhoneShell(false);
    setCompactBack(false);
  });

  it('the Alerts tab opens the history right away', async () => {
    document.body.innerHTML = '';
    window.openManagementSection = vi.fn(() => {
      const win = document.createElement('div');
      win.id = 'management-window';
      win.style.zIndex = '900';
      document.body.appendChild(win);
    });
    enablePhoneShell(true);
    document.querySelector('[data-phone-tab="alerts"]').click();
    await tick();
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-pane-events');
    expect(document.getElementById('phone-alerts-page')).toBeNull(); // no page in between
    // and the bar keeps saying where you are while the history is open
    expect(document.querySelector('.phone-tab.is-current').dataset.phoneTab).toBe('alerts');
    expect(document.querySelector('[data-phone-tab="alerts"]').getAttribute('aria-current')).toBe('page');
    expect(document.querySelectorAll('.phone-tab.is-current').length).toBe(1);
  });

  it('the bar marks the tab at once, also while its page is still loading', async () => {
    document.body.innerHTML = '';
    // the history is loaded when it is first opened: its window comes a moment later
    window.openManagementSection = vi.fn(() => {
      setTimeout(() => {
        const win = document.createElement('div');
        win.id = 'management-window';
        win.style.zIndex = '900';
        document.body.appendChild(win);
      }, 120);
    });
    enablePhoneShell(true);
    document.querySelector('[data-phone-tab="alerts"]').click();
    await tick();
    expect(document.getElementById('management-window')).toBeNull();
    expect(document.querySelector('.phone-tab.is-current').dataset.phoneTab).toBe('alerts'); // it showed Home here
    await vi.waitFor(() => expect(document.getElementById('management-window')).not.toBeNull());
    await tick();
    expect(document.querySelector('.phone-tab.is-current').dataset.phoneTab).toBe('alerts');
    document.getElementById('management-window').remove();
    await tick();
    await tick();
    expect(document.querySelector('.phone-tab.is-current').dataset.phoneTab).toBe('home'); // closed: back where the launcher is
  });

  it('the current tab is marked by its icon and a line, not by its word alone', () => {
    const css = fs.readFileSync(path.join(STYLES, '56-phone.css'), 'utf8');
    expect(css).toMatch(/\.phone-tab \.ic \{[^}]*color: inherit;/);
    expect(css).toMatch(/\.phone-tab\.is-current::before \{[^}]*background: currentColor;/);
  });

  it("the File Explorer's buttons share one row on a phone", () => {
    const css = fs.readFileSync(path.join(STYLES, '49-file-explorer-layout.css'), 'utf8');
    expect(css).toMatch(/\.file-manager-window\) \.fm-toolbar \.fm-nav-btn-group \{ display: contents; \}/);
    expect(css).toMatch(/\.fm-nav-btn-group > \.fm-tool-btn \{ flex: 1 1 0; min-width: 34px; max-width: 56px; \}/);
  });

  it('what needs attention is still a page of its own, with the history one tap away', async () => {
    document.body.innerHTML = '';
    window.openManagementSection = vi.fn();
    enablePhoneShell(true);
    const page = await openAlertsPage();
    expect(page.hidden).toBe(false);
    // the status box comes from a module loaded on demand: wait for it, not one tick (it failed run alone)
    await vi.waitFor(() => expect(page.querySelector('[data-ov-open="storage"]')).not.toBeNull());
    page.querySelector('[data-phone-log]').click();
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-pane-events');
    page.querySelector('.phone-alerts-close').click();
    expect(page.hidden).toBe(true);
  });

  it('Back goes back a folder in Files before it leaves Files', async () => {
    document.body.innerHTML = '';
    enablePhoneShell(true);
    const fm = document.createElement('div');
    fm.className = 'file-manager-window';
    fm.style.zIndex = '1000';
    fm.innerHTML = '<button class="close-btn"></button>';
    let depth = 2;
    fm.zettBack = () => (depth > 0 ? ((depth -= 1), true) : false);
    fm.querySelector('.close-btn').onclick = () => {
      fm.style.display = 'none';
    };
    document.body.appendChild(fm);
    await tick();
    onPhoneBack();
    onPhoneBack();
    await tick();
    expect(depth).toBe(0);
    expect(fm.style.display).not.toBe('none');
    onPhoneBack();
    await tick();
    expect(fm.style.display).toBe('none');
  });

  it('between 601 and 768 px the browser Back closes a full-screen window too', async () => {
    document.body.innerHTML = '';
    const push = vi.spyOn(history, 'pushState');
    setCompactBack(true);
    const w = document.createElement('div');
    w.className = 'os-window';
    w.style.zIndex = '1000';
    w.innerHTML = '<button class="close-btn"></button>';
    w.querySelector('.close-btn').onclick = () => {
      w.style.display = 'none';
    };
    document.body.appendChild(w);
    await tick();
    expect(push).toHaveBeenCalled();
    onPhoneBack();
    await tick();
    expect(w.style.display).toBe('none');
    expect(document.body.classList.contains('phone-page-open')).toBe(false); // no phone chrome here
  });

  it('every stylesheet uses the three widths', () => {
    const allowed = new Set(BREAKPOINTS.flatMap((b) => [b, b + 1]));
    const odd = [];
    for (const f of fs.readdirSync(STYLES).filter((n) => n.endsWith('.css'))) {
      const css = fs.readFileSync(path.join(STYLES, f), 'utf8');
      for (const m of css.matchAll(/@media[^{]*?\((?:max|min)-width:\s*(\d+)px\)/g)) {
        if (!allowed.has(Number(m[1]))) odd.push(`${f}: ${m[1]}px`);
      }
    }
    expect(odd).toEqual([]);
  });
});

describe('UX-36: small text only in the LCD replica', () => {
  it('the tablet sheet keeps 7-11 px text to #console-window', () => {
    const css = fs
      .readFileSync(path.join(STYLES, '24-tablet-bottom-sheet.css'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '');
    const small = [...css.matchAll(/([^{}]+)\{[^{}]*font-size:\s*(\d+(?:\.\d+)?)px/g)].filter((m) => Number(m[2]) < 12);
    const outside = small.filter((m) => !m[1].includes('#console-window')).map((m) => m[1].trim());
    expect(small.length).toBeGreaterThan(0);
    expect(outside).toEqual([]);
  });
});
