// A row that scrolls sideways says so: buttons hidden beyond the edge had no sign of them.
import { describe, it, expect, afterEach } from 'vitest';
import { sidesWithMore, watchSideScroll } from '../side-scroll.js';

function row(scrollWidth, clientWidth, scrollLeft = 0) {
  const el = document.createElement('div');
  let left = scrollLeft;
  Object.defineProperty(el, 'scrollWidth', { configurable: true, get: () => el._w ?? scrollWidth });
  Object.defineProperty(el, 'clientWidth', { configurable: true, get: () => clientWidth });
  Object.defineProperty(el, 'scrollLeft', { configurable: true, get: () => left, set: (v) => (left = v) });
  document.body.append(el);
  return el;
}
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('a row that scrolls sideways', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('knows on which side more is hidden', () => {
    expect(sidesWithMore(row(400, 400))).toBe(''); // everything fits
    expect(sidesWithMore(row(403, 400))).toBe(''); // a pixel or two is not "more"
    expect(sidesWithMore(row(700, 400))).toBe('end');
    expect(sidesWithMore(row(700, 400, 150))).toBe('both');
    expect(sidesWithMore(row(700, 400, 300))).toBe('start'); // at the end
  });

  it('marks the row, and keeps the mark current while it scrolls', () => {
    const el = row(700, 400);
    const stop = watchSideScroll(el);
    expect(el.dataset.more).toBe('end');
    el.scrollLeft = 120;
    el.dispatchEvent(new Event('scroll'));
    expect(el.dataset.more).toBe('both');
    el.scrollLeft = 300;
    el.dispatchEvent(new Event('scroll'));
    expect(el.dataset.more).toBe('start');
    expect(watchSideScroll(el)()).toBeUndefined(); // watched once: a second call changes nothing
    stop();
    expect(el.dataset.more).toBeUndefined();
    el.scrollLeft = 0;
    el.dispatchEvent(new Event('scroll'));
    expect(el.dataset.more).toBeUndefined(); // no longer watched
    expect(watchSideScroll(null)()).toBeUndefined();
  });

  it('notices when a button comes or goes', async () => {
    const el = row(400, 400);
    watchSideScroll(el);
    expect(el.dataset.more).toBe('');
    el._w = 640; // a hidden button was shown
    el.append(document.createElement('button'));
    await flush();
    expect(el.dataset.more).toBe('end');
  });

  it('works where the browser has no ResizeObserver', () => {
    const had = globalThis.ResizeObserver;
    delete globalThis.ResizeObserver;
    try {
      const el = row(700, 400);
      const stop = watchSideScroll(el);
      expect(el.dataset.more).toBe('end');
      stop();
    } finally {
      globalThis.ResizeObserver = had;
    }
  });

  it('is watched with one where the browser has it', async () => {
    const had = globalThis.ResizeObserver;
    const seen = [];
    globalThis.ResizeObserver = class {
      constructor(fn) {
        this.fn = fn;
      }
      observe(el) {
        seen.push(el);
      }
      disconnect() {
        seen.push('stopped');
      }
    };
    try {
      const el = row(700, 400);
      const button = document.createElement('button');
      el.append(button);
      const stop = watchSideScroll(el);
      expect(seen).toEqual([el, button]); // the row and what is in it: a button shown later changes size
      const later = document.createElement('button');
      el.append(later);
      await flush();
      expect(seen).toContain(later);
      stop();
      expect(seen.at(-1)).toBe('stopped');
    } finally {
      globalThis.ResizeObserver = had;
    }
  });
});
