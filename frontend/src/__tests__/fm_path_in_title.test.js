// Phone: the File Explorer's path sits in the title row, next to the window's name (the owner, 19 Nov 2026).
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { placePath } from '../components/file-manager-helpers.js';

const win = () => {
  const el = document.createElement('div');
  el.innerHTML = `<div class="os-window-header"><div class="os-window-title"><span class="fm-title-main">File Explorer</span><span class="fm-title-folder">— appdata</span></div></div>
    <div class="fm-toolbar"><div class="fm-nav-btn-group"><button class="fm-tool-btn fm-up-btn"></button></div><div class="fm-path-container"><input class="fm-path-input" /><div class="fm-path-breadcrumbs"></div></div><button class="fm-tool-btn fm-refresh-btn"></button><div class="fm-search-wrap"></div></div>`;
  return el;
};

describe('the path on a phone', () => {
  it('moves into the title row, and back into the toolbar on a wider screen', () => {
    const el = win();
    const crumbs = el.querySelector('.fm-path-breadcrumbs');
    expect(placePath(el, true)).toBe(true);
    expect(el.querySelector('.os-window-title').lastElementChild.className).toBe('fm-path-container');
    expect(el.querySelector('.fm-toolbar .fm-path-container')).toBeNull();
    expect(el.classList.contains('fm-path-in-title')).toBe(true);
    expect(el.querySelector('.fm-path-breadcrumbs')).toBe(crumbs); // the same element: what was bound to it still is
    // a tap on it there is a tap: the title row does not take it for the start of a drag
    expect(el.querySelector('.fm-path-container').hasAttribute('data-no-drag')).toBe(true);
    const drag = fs.readFileSync(path.resolve(__dirname, '..', 'components', 'dock', 'window-drag.js'), 'utf8');
    expect(drag).toMatch(/e\.target\.closest\('\[data-no-drag\]'\)/);
    placePath(el, true); // again: nothing moves twice
    expect(el.querySelectorAll('.fm-path-container').length).toBe(1);
    expect(placePath(el, false)).toBe(false);
    const order = [...el.querySelector('.fm-toolbar').children].map((c) => c.className.split(' ').pop());
    expect(order).toEqual(['fm-nav-btn-group', 'fm-path-container', 'fm-refresh-btn', 'fm-search-wrap']);
    expect(el.classList.contains('fm-path-in-title')).toBe(false);
  });

  it('leaves a window without these parts alone', () => {
    expect(placePath(document.createElement('div'), true)).toBe(false);
    expect(placePath(null, true)).toBe(false);
  });

  it("the folder's name is not said twice in the title row", () => {
    const css = fs.readFileSync(path.resolve(__dirname, '..', 'styles', '49-file-explorer-layout.css'), 'utf8');
    expect(css).toMatch(/\.fm-path-in-title \.os-window-title \.fm-title-folder \{ display: none; \}/);
    expect(css).toMatch(/\.fm-path-in-title \.os-window-title \.fm-path-container \{[^}]*flex: 1 1 0;/);
  });
});
