import { describe, it, expect, vi, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { followTabsHeight } from '../components/phone-shell.js';

describe('messages above the phone tabs', () => {
  afterEach(() => {
    followTabsHeight(null);
    vi.unstubAllGlobals();
  });

  it('keeps the tabs real height for the CSS and follows it as it changes', () => {
    let seen = null;
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(cb) {
          seen = cb;
        }
        observe() {}
        disconnect() {}
      }
    );
    const tabs = document.createElement('nav');
    let h = 61.4;
    tabs.getBoundingClientRect = () => /** @type {DOMRect} */ ({ height: h });
    followTabsHeight(tabs);
    expect(document.documentElement.style.getPropertyValue('--phone-tabs-h')).toBe('62px');
    h = 96;
    seen();
    expect(document.documentElement.style.getPropertyValue('--phone-tabs-h')).toBe('96px');
    followTabsHeight(null);
    expect(document.documentElement.style.getPropertyValue('--phone-tabs-h')).toBe('');
  });

  it('puts messages above and in front of the tabs, over the stacked layout rule', () => {
    const css = readFileSync(resolve(__dirname, '..', 'styles/56-phone.css'), 'utf8');
    const rule = css.slice(css.indexOf('body.phone-shell #top-toast-container {'));
    expect(rule).toMatch(/bottom: calc\(var\(--phone-tabs-h[^;]*!important/);
    expect(rule).toMatch(/z-index: 10070 !important/); // the tabs are at 10050
  });
});
