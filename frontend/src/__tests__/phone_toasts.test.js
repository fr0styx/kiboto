import { describe, it, expect, vi, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { followTopBar } from '../components/phone-shell.js';

describe('messages at the top on a phone', () => {
  afterEach(() => {
    followTopBar(null);
    vi.unstubAllGlobals();
  });

  it('keeps where the top bar ends for the CSS and follows it as it changes', () => {
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
    const bar = document.createElement('header');
    let bottom = 55.2;
    bar.getBoundingClientRect = () => /** @type {DOMRect} */ ({ bottom });
    followTopBar(bar);
    expect(document.documentElement.style.getPropertyValue('--phone-top-h')).toBe('56px');
    bottom = 80;
    seen();
    expect(document.documentElement.style.getPropertyValue('--phone-top-h')).toBe('80px');
    followTopBar(null);
    expect(document.documentElement.style.getPropertyValue('--phone-top-h')).toBe('');
  });

  it('puts messages under the top bar and in front, over the stacked layout rule', () => {
    const css = readFileSync(resolve(__dirname, '..', 'styles/56-phone.css'), 'utf8');
    const rule = css.slice(css.indexOf('body.phone-shell #top-toast-container {'));
    expect(rule).toMatch(/top: calc\(var\(--phone-top-h[^;]*!important/);
    expect(rule).toMatch(/bottom: auto !important/);
    expect(rule).toMatch(/z-index: 10070 !important/); // the tabs are at 10050
  });
});
