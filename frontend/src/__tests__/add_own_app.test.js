// Apps decision 3 with 4b: "Add your own app" from a Compose file, through the safe apply.
import { describe, it, expect, vi } from 'vitest';

const applied = [];
let result = true;
vi.mock('../components/stack-apply.js', () => ({
  applyStack: async (name, compose, env, opts) => { applied.push({ name, compose, env, create: opts.create }); return result; },
}));

const { nameProblem, openAddOwnApp } = await import('../components/add-own-app.js');
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('add your own app', () => {
  it('checks the name', () => {
    expect(nameProblem('')).toBe('Give the app a name.');
    expect(nameProblem('My App')).toMatch(/^Use small letters/);
    expect(nameProblem('-x')).toMatch(/^Use small letters/);
    expect(nameProblem('my-app_2')).toBe('');
  });

  it('asks for a name and a file, then creates through the safe apply', async () => {
    const done = vi.fn();
    const dlg = openAddOwnApp({ done });
    const $ = (id) => /** @type {any} */ (dlg.querySelector(`#${id}`));
    const submit = () => $('own-app-form').dispatchEvent(new Event('submit', { cancelable: true }));
    submit();
    expect($('own-app-msg').textContent).toBe('Give the app a name.');
    $('own-app-name').value = 'web';
    submit();
    expect($('own-app-msg').textContent).toBe('Paste the Compose file.');
    $('own-app-compose').value = 'services:\n  web:\n    image: nginx:1.27\n';
    $('own-app-envtext').value = 'TZ=UTC';
    result = false;
    submit();
    await flush();
    expect(applied.at(-1)).toEqual({ name: 'web', compose: 'services:\n  web:\n    image: nginx:1.27\n', env: 'TZ=UTC', create: true });
    expect(document.getElementById('own-app-dialog')).not.toBeNull(); // kept open when not created
    result = true;
    submit();
    await flush();
    expect(document.getElementById('own-app-dialog')).toBeNull();
  });

  it('cancel closes it, and opening again starts fresh', () => {
    const first = openAddOwnApp();
    const second = openAddOwnApp();
    expect(document.querySelectorAll('#own-app-dialog')).toHaveLength(1);
    expect(first.isConnected).toBe(false);
    /** @type {HTMLElement} */ (second.querySelector('#own-app-cancel')).click();
    expect(document.getElementById('own-app-dialog')).toBeNull();
  });
});
