/** SET-25 Apps 4: the detail dialog shows Overview, Folders and Log to everyone; the rest with Docker details. */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { markDetailTabs, EVERYDAY_TABS } from '../components/container-modal.js';

const TABS = ['overview', 'ports', 'mounts', 'env', 'compose', 'logs', 'terminal', 'edit'];
const strip = () => {
  document.body.innerHTML = `<div class="ci-nav-tabs">${TABS.map((t) => `<button class="ci-tab-btn" data-tab="${t}"></button>`).join('')}</div>`;
  return document.body;
};
const shown = () => [...document.querySelectorAll('.ci-tab-btn')].filter((b) => !b.hidden).map((b) => b.dataset.tab);

describe('detail tabs by Docker details (SET-25)', () => {
  it('the household view has the three everyday tabs', () => {
    markDetailTabs(strip(), false);
    expect(shown()).toEqual(['overview', 'mounts', 'logs']);
    expect(EVERYDAY_TABS).toEqual(['overview', 'mounts', 'logs']);
  });

  it('Docker details shows all eight', () => {
    const root = strip();
    markDetailTabs(root, false);
    markDetailTabs(root, true);
    expect(shown()).toEqual(TABS);
  });

  it('a tab asked for by name stays, so "Change settings" still opens Edit', () => {
    markDetailTabs(strip(), false, 'edit');
    expect(shown()).toEqual(['overview', 'mounts', 'logs', 'edit']);
  });

  it('on a phone the action row starts with "Get apps", and the tab strip wraps on a desktop', () => {
    const css = fs.readFileSync(path.resolve(__dirname, '../styles/containers-lazy.css'), 'utf8');
    expect(css).toMatch(/@media \(max-width: 768px\) \{ \.cw-action-btns-wrap > #btn-cw-catalog \{ order: -1; \} \}/);
    expect(css).toMatch(/\.ci-nav-tabs \{ flex-wrap: wrap; \}/);
  });
});
