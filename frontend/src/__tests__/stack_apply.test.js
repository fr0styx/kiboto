/** Apps decision 4b: Apply shows what will happen, then follows the job to the end. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { stepLines, applyQuestion, followJob, applyStack } from '../components/stack-apply.js';
import { api } from '../api.js';
import { showToast, showConfirmToast } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));
const now = async () => {};

const PREVIEW = {
  steps: [
    { service: 'db', action: 'keep', image: 'postgres:16' },
    { service: 'web', action: 'replace', image: 'nginx:1.27', why: ['image nginx:1.26 → nginx:1.27', 'ports'] },
    { service: 'cache', action: 'new', image: 'redis:7' },
    { service: 'old', action: 'remove' },
  ],
  elevated: [{ service: 'web', reasons: ['privileged'] }],
};

describe('Apply a stack (Apps decision 4b)', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("says each service's change in words, and the host access", () => {
    expect(stepLines(PREVIEW.steps)).toEqual([
      'Kept as it is: db',
      'Replaced: web (image nginx:1.26 → nginx:1.27, ports)',
      'New: cache (redis:7)',
      'Removed: old',
    ]);
    const q = applyQuestion(PREVIEW);
    expect(q).toContain('web gets access to the host: privileged');
    expect(q).toContain('everything goes back as it was');
    expect(stepLines(undefined)).toEqual([]);
  });

  it('follows the job to its end', async () => {
    vi.spyOn(api, 'get')
      .mockResolvedValueOnce({ active: [{ id: 'job:1', status: 'running' }] })
      .mockRejectedValueOnce(new Error('x'))
      .mockResolvedValueOnce({ history: [{ id: 'job:1', status: 'error', error: 'web stopped' }] });
    expect(await followJob('job:1', now)).toEqual({ status: 'error', error: 'web stopped' });
    vi.spyOn(api, 'get').mockResolvedValue({ active: [] });
    expect(await followJob('job:9', now, 2)).toEqual({ status: 'unknown', error: '' });
  });

  it('asks, applies, and says how it ended', async () => {
    const msg = document.createElement('div');
    const post = vi
      .spyOn(api, 'post')
      .mockImplementation(async (url) => (url.endsWith('/preview') ? PREVIEW : { status: 'started', job: 'job:1' }));
    vi.spyOn(api, 'get').mockResolvedValue({ history: [{ id: 'job:1', status: 'done' }] });
    showConfirmToast.mockImplementation((title, body, ok) => ok());
    const done = vi.fn();
    expect(await applyStack('shop', 'services: {}', '', { msg, done, wait: now })).toBe(true);
    expect(showConfirmToast.mock.calls[0][0]).toBe('Apply this file to shop?');
    expect(showConfirmToast.mock.calls[0][4]).toEqual({ okText: 'Apply', isDanger: true });
    expect(post).toHaveBeenLastCalledWith(
      '/api/docker/stacks/shop/apply',
      { compose_yaml: 'services: {}', env_content: '' },
      { confirmed: true }
    );
    expect(msg.textContent).toBe('shop is applied.');
    expect(done).toHaveBeenCalled();
    vi.spyOn(api, 'get').mockResolvedValue({
      history: [{ id: 'job:1', status: 'error', error: 'web stopped. Everything is back as it was.' }],
    });
    expect(await applyStack('shop', 'x', '', { msg, wait: now })).toBe(false);
    expect(showToast).toHaveBeenLastCalledWith(
      'shop was not applied: web stopped. Everything is back as it was.',
      'error'
    );
    vi.spyOn(api, 'get').mockResolvedValue({ history: [{ id: 'job:1', status: 'cancelled' }] });
    await applyStack('shop', 'x', '', { wait: now });
    expect(showToast).toHaveBeenLastCalledWith(
      'shop was not applied: Kiboto could not tell how it ended; look in Jobs.',
      'error'
    );
  });

  it('stops early: preview refused, nothing to change, a no, or a refused apply', async () => {
    const msg = document.createElement('div');
    vi.spyOn(api, 'post').mockRejectedValueOnce(new Error('Kiboto cannot apply build yet.'));
    expect(await applyStack('s', 'x', '', { msg })).toBe(false);
    expect(msg.textContent).toBe('Kiboto cannot apply build yet.');
    api.post.mockResolvedValueOnce({ steps: [{ service: 'db', action: 'keep' }], elevated: [] });
    expect(await applyStack('s', 'x', '')).toBe(false);
    expect(showToast).toHaveBeenLastCalledWith('Nothing to change: the containers already match the file.', 'info');
    api.post.mockResolvedValueOnce({ steps: [{ service: 'db', action: 'new' }] });
    showConfirmToast.mockImplementationOnce((title, body, ok, no) => no());
    expect(await applyStack('s', 'x', '')).toBe(false);
    api.post
      .mockResolvedValueOnce({ steps: [{ service: 'db', action: 'new' }] })
      .mockRejectedValueOnce(new Error('denied'));
    showConfirmToast.mockImplementationOnce((title, body, ok) => ok());
    expect(await applyStack('s', 'x', '', { msg })).toBe(false);
    expect(msg.textContent).toBe('denied');
  });
});
