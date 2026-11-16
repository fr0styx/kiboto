/** Audit A7: the invite landing loads only for an invite address, off the first load. */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('invite landing off the first load (audit A7)', () => {
  it('main.js imports it on demand, for #/invite/ addresses only', () => {
    const main = readFileSync(resolve(__dirname, '../main.js'), 'utf8');
    expect(main).not.toMatch(/^import .*invites\.js/m);
    expect(main).toContain("if (window.location.hash.startsWith('#/invite/')) import('./components/invites.js')");
  });
});
