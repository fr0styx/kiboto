// Recovery key (Security): shown until written down, typed when the machine could not open its key.
import { describe, it, expect, vi, beforeEach } from 'vitest';

let state;
const posts = [];
let postFails = null;
vi.mock('../api.js', () => ({
  api: {
    get: async () => {
      if (state instanceof Error) throw state;
      return state;
    },
    post: async (url, body) => {
      posts.push([url, body]);
      if (postFails) throw postFails;
      if (url.endsWith('/recovery-key')) return { recovery_key: 'ABCD-EFGH-JKLM-NPQR-STUV-WXYZ' };
      if (url.endsWith('/written-down')) state = { ...state, to_write_down: false, written_down_at: 1795264825 };
      if (url.endsWith('/new-recovery-key')) state = { ...state, to_write_down: true, written_down_at: null };
      if (url.endsWith('/unlock')) state = { ...state, locked: false };
      return { ...state, restarting: true };
    },
  },
}));

const { renderRecoveryKeyCard, recoveryKeyStatus } = await import('../components/recovery-key-card.js');

const flush = () => new Promise((r) => setTimeout(r, 0));
const mount = () => /** @type {HTMLElement} */ (document.getElementById('recovery-key-card'));
const el = (id) => /** @type {any} */ (mount().querySelector(`#${id}`));

beforeEach(() => {
  posts.length = 0;
  postFails = null;
  state = { managed: true, on: true, locked: false, sealed_to: 'chip', to_write_down: true, written_down_at: null };
  document.body.innerHTML = '<section id="recovery-key-card" hidden></section>';
});

describe('Recovery key', () => {
  it('says where things stand', () => {
    expect(recoveryKeyStatus({ locked: true })).toContain('Type the recovery key to open them.');
    expect(recoveryKeyStatus({ to_write_down: true })).toBe(
      'Write the recovery key down and keep it away from this machine.'
    );
    expect(recoveryKeyStatus({ written_down_at: 1795264825 })).toMatch(/^Written down on .*2026/);
    expect(recoveryKeyStatus({})).toBe('');
  });

  it('stays hidden where Kiboto is a guest, where there is no key, and when it cannot be read', async () => {
    for (const st of [{ managed: false }, { managed: true, on: false }, new Error('403')]) {
      state = st;
      await renderRecoveryKeyCard();
      expect(mount().hidden).toBe(true);
      expect(mount().innerHTML).toBe('');
    }
    document.body.innerHTML = '';
    expect(await renderRecoveryKeyCard()).toBe(null);
  });

  it('shows the key only when asked, and forgets it once it is written down', async () => {
    await renderRecoveryKeyCard();
    expect(mount().hidden).toBe(false);
    expect(mount().textContent).toContain("sealed to this machine's security chip");
    expect(el('rkey-code').hidden).toBe(true);
    expect(mount().textContent).not.toContain('ABCD-EFGH');
    el('rkey-show').click();
    await flush();
    expect(el('rkey-code').textContent).toBe('ABCD-EFGH-JKLM-NPQR-STUV-WXYZ');
    expect(el('rkey-code').hidden).toBe(false);
    expect(el('rkey-show').hidden).toBe(true);
    el('rkey-written').click();
    await flush();
    expect(posts.map((p) => p[0])).toEqual([
      '/api/system/machine/key/recovery-key',
      '/api/system/machine/key/written-down',
    ]);
    expect(el('rkey-status').textContent).toMatch(/^Written down on /);
    expect(mount().textContent).not.toContain('ABCD-EFGH');
    expect(el('rkey-new')).not.toBeNull();
  });

  it('says where the key is kept on a machine without a security chip', async () => {
    state = { ...state, sealed_to: 'disk', to_write_down: false, written_down_at: 1795264825 };
    await renderRecoveryKeyCard();
    expect(mount().textContent).toContain('This machine has no security chip');
  });

  it('makes a new key when asked, and stays as it is when the person says no', async () => {
    state = { ...state, to_write_down: false, written_down_at: 1795264825 };
    await renderRecoveryKeyCard();
    postFails = { error: 'cancelled' };
    el('rkey-new').click();
    await flush();
    expect(el('rkey-error').hidden).toBe(true);
    expect(el('rkey-new')).not.toBeNull();
    postFails = null;
    el('rkey-new').click();
    await flush();
    expect(posts.at(-1)[0]).toBe('/api/system/machine/key/new-recovery-key');
    expect(el('rkey-show')).not.toBeNull(); // the new key waits to be written down
  });

  it('opens a locked machine with the typed key, and says when the key is wrong', async () => {
    state = { ...state, locked: true, to_write_down: false };
    await renderRecoveryKeyCard();
    expect(el('rkey-status').textContent).toContain('could not open its data key');
    el('rkey-input').value = '  abcd efgh jklm npqr stuv wxyz ';
    postFails = new Error("That is not this machine's recovery key.");
    el('rkey-form').dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(el('rkey-error').textContent).toBe("That is not this machine's recovery key.");
    expect(el('rkey-error').hidden).toBe(false);
    postFails = {};
    el('rkey-form').dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(el('rkey-error').textContent).toBe('That did not work.');
    postFails = null;
    el('rkey-form').dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(posts.at(-1)).toEqual(['/api/system/machine/key/unlock', { recovery_key: 'abcd efgh jklm npqr stuv wxyz' }]);
    expect(el('rkey-status').textContent).toBe('Opened. Kiboto is starting again; this page comes back in a moment.');
    expect(el('rkey-form').hidden).toBe(true);
    expect(el('rkey-error').hidden).toBe(true);
  });
});
