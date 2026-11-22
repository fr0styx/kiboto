// Settings copy on your pools (Backup): per pool when it was written; never wakes a sleeping pool.
// And the way back: look on the drives, then the recovery key brings an earlier Kiboto's settings back.
import { describe, it, expect, vi, beforeEach } from 'vitest';

let state;
let answers;
const posts = [];
vi.mock('../api.js', () => ({
  api: {
    get: async () => {
      if (state instanceof Error) throw state;
      return state;
    },
    post: async (url, body) => {
      posts.push([url, body]);
      const answer = answers[url.split('/').pop()];
      if (answer instanceof Error) throw answer;
      return answer;
    },
  },
}));

const { renderPoolCopyCard, poolCopyLine } = await import('../components/pool-copy-card.js');

const flush = () => new Promise((r) => setTimeout(r, 0));
const mount = () => /** @type {HTMLElement} */ (document.getElementById('pool-copy-card'));
const el = (id) => /** @type {any} */ (mount().querySelector(`#${id}`));
const lines = (sel = '.pcopy-list') =>
  [...mount().querySelectorAll(`${sel} li`)].map((li) => li.textContent?.replace(/\s+/g, ' ').trim());
const COPY = { key: 'feedfacefeedface-tank', name: 'attic', version: '2.0.5', at: 1795265867, pool: 'tank' };

beforeEach(() => {
  posts.length = 0;
  state = {
    managed: true,
    locked: false,
    pools: [
      { name: 'tank', at: 1795265867, error: '' },
      { name: 'media', at: 0, error: '' },
    ],
    found: [],
  };
  answers = {
    now: { ...state, done: { tank: 'copied', media: 'asleep' } },
    look: { found: [COPY] },
    restore: { restored: 38, name: 'attic', pool: 'tank', restarting: true },
  };
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
    expect(lines()[0]).toMatch(/^tank Copied /);
    expect(lines()[1]).toBe('media No copy yet');
    expect(el('pcopy-now').disabled).toBe(false);
    el('pcopy-now').click();
    await flush();
    expect(lines()[1]).toBe('media Asleep: it keeps the copy it has');
  });

  it('says why a copy now did not work and lets the person try again', async () => {
    await renderPoolCopyCard();
    answers.now = new Error('The machine could not open its data key.');
    el('pcopy-now').click();
    await flush();
    expect(el('pcopy-error').hidden).toBe(false);
    expect(el('pcopy-error').textContent).toBe('The machine could not open its data key.');
    expect(el('pcopy-now').disabled).toBe(false);
  });

  it('has nothing to copy before the first pool, and cannot copy while the key is locked', async () => {
    state = { managed: true, locked: false, pools: [] };
    await renderPoolCopyCard();
    expect(el('pcopy-none').textContent).toContain('No pools yet');
    expect(el('pcopy-now').disabled).toBe(true);
    expect(el('pcopy-now').title).toContain('No pools yet'); // a button that cannot be pressed says why
    state = { managed: true, locked: true, pools: [{ name: 'tank', at: 0, error: '' }] };
    await renderPoolCopyCard();
    expect(el('pcopy-locked').textContent).toContain('recovery key');
    expect(el('pcopy-now').disabled).toBe(true);
    state = { managed: true };
    await renderPoolCopyCard();
    expect(el('pcopy-now').disabled).toBe(true);
  });
});

describe('Settings from an earlier Kiboto', () => {
  it('looks only when asked and says so when nothing was found', async () => {
    await renderPoolCopyCard();
    expect(posts).toEqual([]);
    expect(el('pcopy-found')).toBeNull();
    expect(el('pcopy-nothing')).toBeNull(); // nobody has looked yet
    answers.look = { found: [] };
    el('pcopy-look').click();
    expect(el('pcopy-look').disabled).toBe(true);
    expect(el('pcopy-look').textContent).toBe('Looking…');
    await flush();
    expect(posts).toEqual([['/api/system/settings-copy/look', {}]]);
    expect(el('pcopy-nothing').textContent).toContain('No settings of an earlier Kiboto were found');
    expect(el('pcopy-look').disabled).toBe(false);
  });

  it('says why looking failed and lets the person look again', async () => {
    await renderPoolCopyCard();
    answers.look = new Error('The drives could not be read.');
    el('pcopy-look').click();
    await flush();
    expect(el('pcopy-error').textContent).toBe('The drives could not be read.');
    expect(el('pcopy-look').disabled).toBe(false);
    expect(el('pcopy-look').textContent).toBe('Look on the drives');
  });

  it('brings a found copy back with the recovery key of the Kiboto that wrote it', async () => {
    await renderPoolCopyCard();
    el('pcopy-look').click();
    await flush();
    expect(lines('#pcopy-found')[0]).toMatch(/^attic, copied .*2026.*, on pool tank Bring back$/);
    expect(el('pcopy-restore').hidden).toBe(true);
    /** @type {HTMLElement} */ (mount().querySelector('.pcopy-bring')).click();
    expect(el('pcopy-restore').hidden).toBe(false);
    expect(el('pcopy-restore-note').textContent).toContain(
      'replaces the settings this Kiboto has now with those of attic'
    );
    expect(el('pcopy-restore-label').textContent).toBe('The recovery key of attic');
    el('pcopy-restore-key').value = ' abcd-efgh-jklm-npqr-stuv-wxyz ';
    answers.restore = new Error("That is not this machine's recovery key.");
    el('pcopy-restore').dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(el('pcopy-error').textContent).toBe("That is not this machine's recovery key.");
    expect(el('pcopy-restore-go').disabled).toBe(false);
    answers.restore = { restored: 38, name: 'attic', pool: 'tank', restarting: true };
    el('pcopy-restore').dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(posts.at(-1)).toEqual([
      '/api/system/settings-copy/restore',
      { key: 'feedfacefeedface-tank', recovery_key: 'abcd-efgh-jklm-npqr-stuv-wxyz' },
    ]);
    expect(el('pcopy-error').hidden).toBe(true);
    expect(el('pcopy-restore').hidden).toBe(true);
    expect(el('pcopy-restore-done').textContent).toContain('The settings of attic are coming back');
    expect(el('pcopy-restore-done').hidden).toBe(false);
  });

  it('shows what an earlier look found, lets the person change their mind, and names the copy when the answer does not', async () => {
    state = { ...state, found: [COPY] };
    await renderPoolCopyCard();
    expect(lines('#pcopy-found')).toHaveLength(1);
    /** @type {HTMLElement} */ (mount().querySelector('.pcopy-bring')).click();
    el('pcopy-restore-key').value = 'abcd';
    el('pcopy-restore-cancel').click();
    expect(el('pcopy-restore').hidden).toBe(true);
    expect(el('pcopy-restore-key').value).toBe('');
    /** @type {HTMLElement} */ (mount().querySelector('.pcopy-bring')).click();
    answers.restore = { restored: 38 };
    el('pcopy-restore').dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(el('pcopy-restore-done').textContent).toContain('The settings of attic are coming back');
    answers.restore = 'a plain value, not an error object';
  });
});
