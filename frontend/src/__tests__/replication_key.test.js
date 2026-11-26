// A copy to another machine signs in with a key of its own: the form shows it, to add there.
import { describe, it, expect, vi, beforeEach } from 'vitest';

let answer;
vi.mock('../api.js', () => ({
  api: {
    get: async () => {
      if (answer instanceof Error) throw answer;
      return answer;
    },
  },
}));

const { showReplicationKey } = await import('../components/replication-key.js');

beforeEach(() => {
  document.body.innerHTML = '<p id="repl-key-help" hidden></p><code id="repl-key" hidden></code>';
});

describe('the replication key', () => {
  it('is shown with its help when the server has one', async () => {
    answer = { public_key: 'ssh-ed25519 AAAA kiboto-replication' };
    expect(await showReplicationKey()).toBe('ssh-ed25519 AAAA kiboto-replication');
    expect(document.getElementById('repl-key').textContent).toBe('ssh-ed25519 AAAA kiboto-replication');
    expect(document.getElementById('repl-key-help').hidden).toBe(false);
  });

  it('stays hidden when there is none or the server cannot say', async () => {
    answer = { public_key: '' };
    expect(await showReplicationKey()).toBe('');
    expect(document.getElementById('repl-key').hidden).toBe(true);
    answer = new Error('403');
    expect(await showReplicationKey()).toBe('');
    document.body.innerHTML = '';
    expect(await showReplicationKey()).toBe('');
  });
});
