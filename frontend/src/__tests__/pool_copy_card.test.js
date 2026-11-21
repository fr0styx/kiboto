// Settings copy on your pools (Backup): per pool when it was written; never wakes a sleeping pool.
import { describe, it, expect, vi, beforeEach } from 'vitest';

let state;
let now;
vi.mock('../api.js', () => ({
  api: {
    get: async () => {
      if (state instanceof Error) throw state;
      return state;
    },
    post: async () => {
      if (now instanceof Error) throw now;
      return now;
    },
  },
}));

const { renderPoolCopyCard, poolCopyLine } = await import('../components/pool-copy-card.js');

const flush = () => new Promise((r) => setTimeout(r, 0));
const mount = () => /** @type {HTMLElement} */ (document.getElementById('pool-copy-card'));
const button = () => /** @type {HTMLButtonElement} */ (mount().querySelector('#pcopy-now'));

beforeEach(() => {
  state = {
    managed: true,
    locked: false,
    pools: [
      { name: 'tank', at: 1795265867, error: '' },
      { name: 'media', at: 0, error: '' },
    ],
  };
  now = { ...state, done: { tank: 'copied', media: 'asleep' } };
  document.body.innerHTML = '<section id="pool-copy-card" hidden></section>';
});

describe('Settings copy on your pools', () => {
  it('says per pool where its copy stands', () => {
    expect(poolCopyLine({ at: 1795265867 })).toMatch(/^Copied .*2026/);
    expect(poolCopyLine({ at: 0 })).toBe('No copy yet');
    expect(poolCopyLine({ at: 1795265867, error: 'No space left' })).toBe('Last try failed: No space left');
    expect(poolCopyLine({ at: 1795265867 }, 'asleep')).toBe('Asleep: it keeps the copy it has');
  });

  it('stays hidden where Kiboto is a guest and when it cannot be read', async () => {
    for (const st of [{ managed: false }, new Error('403')]) {
      state = st;
      await renderPoolCopyCard();
      expect(mount().hidden).toBe(true);
      expect(mount().innerHTML).toBe('');
    }
    document.body.innerHTML = '';
    expect(await renderPoolCopyCard()).toBe(null);
  });

  it('lists the pools, copies now and says which pool was left asleep', async () => {
    await renderPoolCopyCard();
    expect(mount().hidden).toBe(false);
    const lines = () =>
      [...mount().querySelectorAll('.pcopy-list li')].map((li) => li.textContent?.replace(/\s+/g, ' '));
    expect(lines()[0]).toMatch(/^tank Copied /);
    expect(lines()[1]).toBe('media No copy yet');
    expect(button().disabled).toBe(false);
    button().click();
    await flush();
    expect(lines()[1]).toBe('media Asleep: it keeps the copy it has');
  });

  it('says why a copy now did not work and lets the person try again', async () => {
    await renderPoolCopyCard();
    now = new Error('The machine could not open its data key.');
    button().click();
    await flush();
    const err = /** @type {HTMLElement} */ (mount().querySelector('#pcopy-error'));
    expect(err.hidden).toBe(false);
    expect(err.textContent).toBe('The machine could not open its data key.');
    expect(button().disabled).toBe(false);
    now = 'not an error object';
    state = { ...state };
    await renderPoolCopyCard();
    vi.spyOn(Promise, 'resolve'); // nothing to assert on: the next click rejects with a plain value
    now = Object.assign(Object.create(null), {});
    button().click();
    await flush();
    vi.restoreAllMocks();
  });

  it('has nothing to copy before the first pool, and cannot copy while the key is locked', async () => {
    state = { managed: true, locked: false, pools: [] };
    await renderPoolCopyCard();
    expect(mount().querySelector('#pcopy-none')?.textContent).toContain('No pools yet');
    expect(button().disabled).toBe(true);
    expect(button().title).toContain('No pools yet'); // a button that cannot be pressed says why
    state = { managed: true, locked: true, pools: [{ name: 'tank', at: 0, error: '' }] };
    await renderPoolCopyCard();
    expect(mount().querySelector('#pcopy-locked')?.textContent).toContain('recovery key');
    expect(button().disabled).toBe(true);
    state = { managed: true };
    await renderPoolCopyCard();
    expect(button().disabled).toBe(true);
  });
});
