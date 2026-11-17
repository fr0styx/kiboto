// Why the last update did not take, in the reader's language (17 Nov).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../api.js', () => ({
  api: { get: vi.fn() },
  auth: { getToken: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

import { api } from '../api.js';
import { showLastUpdateResult } from '../components/management.js';
import { setLanguage } from '../i18n.js';

describe('Updates panel: the reason in words', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="update-last-result" hidden></div>';
  });
  afterEach(async () => { await setLanguage('en'); });

  it('says the reason in German when the server said how', async () => {
    await setLanguage('de');
    api.get.mockResolvedValueOnce({
      result: 'not_applied',
      reason: 'container exited (code 137)',
      reason_text: { key: 'ev.update_reason.exited', default: 'container exited (code 137)', params: { code: '137' } },
      at: 1700000000,
    });
    await showLastUpdateResult();
    const box = document.getElementById('update-last-result');
    expect(box.hidden).toBe(false);
    expect(box.textContent).toContain('der Container wurde beendet (Code 137)');
    expect(box.textContent).not.toContain('{reason}');
  });

  it('a rollback without a reason leaves no placeholder', async () => {
    api.get.mockResolvedValueOnce({ result: 'rolled_back' });
    await showLastUpdateResult();
    const box = document.getElementById('update-last-result');
    expect(box.hidden).toBe(false);
    expect(box.textContent).not.toContain('{reason}');
    expect(box.textContent).not.toContain('{when}');
  });
});
