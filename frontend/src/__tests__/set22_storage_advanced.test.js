import { describe, it, expect } from 'vitest';
import markup from '../windows/management-window.html?raw';
import fs from 'fs';
import path from 'path';
import { applyAdvancedEverywhere } from '../advanced.js';

describe('Storage: the expert parts follow the Advanced switch (SET-22 Storage 3)', () => {
  it('the page says when Advanced is off', () => {
    applyAdvancedEverywhere(false);
    expect(document.documentElement.classList.contains('kb-advanced-off')).toBe(true);
    applyAdvancedEverywhere(true);
    expect(document.documentElement.classList.contains('kb-advanced-off')).toBe(false);
  });

  it('Create pool and the bay set-up are marked, and the sheet hides them', () => {
    expect(markup).toMatch(/id="btn-create-storage-pool" data-advanced-only/);
    const cv = fs.readFileSync(path.resolve(__dirname, '../components/chassis-visualizer.js'), 'utf8');
    expect(cv).toMatch(/id="chassis-open-slots-btn" data-advanced-only/);
    const css = fs.readFileSync(path.resolve(__dirname, '../styles/management-lazy.css'), 'utf8');
    expect(css).toContain('.kb-advanced-off [data-advanced-only] { display: none !important; }');
  });
});
