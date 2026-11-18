// The window sweep of 18 Nov: a window reopened after a reload could be built before the language
// arrived and stay English, and labels built with t() never caught up. Windows now wait for the texts,
// and labels built from a plain t('key', 'English') carry their key for the translation pass.
import { describe, it, expect, vi } from 'vitest';
import fs from 'fs';
import path from 'path';

const SRC = path.resolve(__dirname, '..');

function sources() {
  const out = [];
  const walk = (dir) => {
    for (const name of fs.readdirSync(dir)) {
      const p = path.join(dir, name);
      if (name === '__tests__' || name === 'locales') continue;
      if (fs.statSync(p).isDirectory()) walk(p);
      else if (name.endsWith('.js')) out.push(p);
    }
  };
  walk(SRC);
  return out;
}

describe('labels follow the language', () => {
  it('a window waits for the texts before building itself', async () => {
    vi.resetModules();
    const { lazyWindow, whenTextsReady } = await import('../lazy-windows.js');
    let release;
    whenTextsReady(
      new Promise((r) => {
        release = r;
      })
    );
    const init = vi.fn();
    const ensure = lazyWindow({ id: 'probe-window', load: async () => ({ initProbe: init }), init: 'initProbe' });
    const opened = ensure();
    await new Promise((r) => setTimeout(r, 20));
    expect(init).not.toHaveBeenCalled();
    release();
    await opened;
    expect(init).toHaveBeenCalledTimes(1);
  });

  it('a language that fails to load does not keep windows shut', async () => {
    vi.resetModules();
    const { lazyWindow, whenTextsReady } = await import('../lazy-windows.js');
    whenTextsReady(Promise.reject(new Error('offline')));
    const init = vi.fn();
    await lazyWindow({ id: 'probe-window-2', load: async () => ({ initProbe: init }), init: 'initProbe' })();
    expect(init).toHaveBeenCalledTimes(1);
  });

  it('every label built from a plain t() carries its key', () => {
    const plain = /(aria-label|(?<![\w-])title)="\$\{(?:escapeHtml\()?t\('([\w.-]+)', '(?:[^'\\]|\\.)*'\)\)?\}"/g;
    const missing = [];
    for (const file of sources()) {
      const src = fs.readFileSync(file, 'utf8');
      for (const m of src.matchAll(plain)) {
        const start = src.lastIndexOf('<', m.index);
        const end = src.indexOf('>', m.index + m[0].length);
        const tag = src.slice(start, end);
        const want = m[1] === 'aria-label' ? 'data-i18n-aria-label' : 'data-i18n-title';
        // three buttons change their own label with their state: those keep it out of the pass
        if (/id="(ql-maximize-btn|quicklook-copy-btn|vm-console-kbd-pill)"/.test(tag)) continue;
        if (!tag.includes(want)) missing.push(`${path.relative(SRC, file)}: ${m[2]}`);
      }
    }
    expect(missing).toEqual([]);
  });
});
