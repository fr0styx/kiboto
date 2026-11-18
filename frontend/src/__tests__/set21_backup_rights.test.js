import { describe, it, expect } from 'vitest';
import { applyNeeds, NEEDS } from '../components/backup-needs.js';

const PAGE = `<div id="p">
  <button data-off="connect"></button><button data-off="everything"></button><button data-off="backup"></button>
  <button data-rd="all"></button><button data-rd="file"></button>
  <div data-off-usb></div><button id="btn-backup-download"></button><div class="bk-upload"></div>
  <input data-scrub-pool="p1"></div>`;
const hiddenOnes = (root) =>
  [...root.querySelectorAll('[data-no-access]')].map(
    (e) =>
      e.getAttribute('data-off') ||
      e.getAttribute('data-rd') ||
      e.id ||
      e.className ||
      (e.hasAttribute('data-off-usb') ? 'usb' : 'scrub')
  );

describe('Backup buttons follow the rights (SET-21, Backup B9)', () => {
  it('a backup manager does not see what only answers "not allowed"', () => {
    document.body.innerHTML = PAGE;
    const root = /** @type {HTMLElement} */ (document.getElementById('p'));
    expect(applyNeeds(root, { scopes: ['backup:read', 'backup:manage'] })).toBe(NEEDS.length);
    expect(hiddenOnes(root)).not.toContain('backup');
    expect(hiddenOnes(root)).not.toContain('file');
    expect(root.querySelector('[data-off="connect"]')?.hasAttribute('data-no-access')).toBe(true);
  });

  it('the owner sees everything; an unknown account is left alone', () => {
    document.body.innerHTML = PAGE;
    const root = /** @type {HTMLElement} */ (document.getElementById('p'));
    expect(applyNeeds(root, { scopes: ['*'] })).toBe(0);
    expect(applyNeeds(root, null)).toBe(0);
  });

  it('a storage admin keeps the monthly check', () => {
    document.body.innerHTML = PAGE;
    const root = /** @type {HTMLElement} */ (document.getElementById('p'));
    applyNeeds(root, { scopes: ['storage:admin', 'backup:read'] });
    expect(root.querySelector('[data-scrub-pool]')?.hasAttribute('data-no-access')).toBe(false);
  });
});
