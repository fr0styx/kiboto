import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const html = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');

describe("People's layout (SET-19, Users report section 5)", () => {
  it('one button in the header, the family set-ups together, the rest under a closed Advanced', () => {
    document.body.innerHTML = html;
    const list = /** @type {HTMLElement} */ (document.getElementById('users-pane-list'));
    expect([...list.querySelectorAll('.users-bar-actions button')].map((b) => b.id)).toEqual(['btn-add-user']);
    expect(document.getElementById('btn-refresh-users')).toBeNull();
    const order = [...list.querySelectorAll('h3, h4, details')].map((e) => e.getAttribute('data-i18n') || e.className);
    expect(order.indexOf('hh.title')).toBeLessThan(order.indexOf('people.for_family'));
    expect(list.querySelector('#people-family-links')).not.toBeNull(); // the set-ups live in Apps; People keeps link rows (SET-19 stage 5)
    expect(order.indexOf('ff.title')).toBe(-1);
    expect(order.indexOf('users.away_title')).toBeGreaterThan(order.indexOf('fs.title'));
    expect(order.at(-1)).toBe('people-advanced');
    const advanced = /** @type {HTMLDetailsElement} */ (list.querySelector('.people-advanced'));
    expect(advanced.open).toBe(false);
    expect(advanced.querySelector('#btn-share-access')).not.toBeNull();
    expect([...advanced.querySelectorAll('a')].map((a) => a.getAttribute('href'))).toEqual([
      '#/security',
      '#/security',
    ]);
  });
});
