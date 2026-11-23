import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { titleIconOf } from '../components/management.js';

describe('Kib shown as itself in Settings', () => {
  it('the window title icon follows the page', () => {
    document.body.innerHTML = `
      <div id="management-window-header"><svg class="mgmt-title-ic"><use href="#i-management"/></svg></div>
      <button class="mgmt-sidebar-item" data-mgmt-target="mgmt-sec-ai"><svg><use href="#i-kib"/></svg></button>`;
    const use = document.querySelector('.mgmt-title-ic use');
    titleIconOf('mgmt-sec-ai');
    expect(use.getAttribute('href')).toBe('#i-kib');
    titleIconOf('mgmt-sec-nowhere');
    expect(use.getAttribute('href')).toBe('#i-management');
    titleIconOf('mgmt-sec-ai');
    titleIconOf('');
    expect(use.getAttribute('href')).toBe('#i-management');
  });

  it('the Kib page starts with Kib: its face, its name, what it does and Open Kib', () => {
    const html = readFileSync(resolve(__dirname, '..', 'windows/management-window.html'), 'utf8');
    const pane = html.slice(html.indexOf('id="mgmt-pane-ai-index"'), html.indexOf('id="kib-status-mount"'));
    expect(pane).toContain('class="kib-hero"');
    expect(pane).toContain('kib-buddy-eye');
    expect(pane).toContain('data-i18n="kibw.hero_line"');
    expect(pane).toContain('data-kib-open');
  });
});
