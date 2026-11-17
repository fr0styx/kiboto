// A Security Advisor fix says what it did in the reader's language (17 Nov).
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../api.js', () => ({
  api: { get: vi.fn().mockResolvedValue({ checks: [] }), post: vi.fn() },
  auth: { getToken: vi.fn() },
  ApiError: class ApiError extends Error {},
}));
vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), hideConfirmToast: vi.fn() }));

import { api } from '../api.js';
import { showToast } from '../toast.js';
import { applySecurityFix } from '../components/management/security.js';
import { setLanguage } from '../i18n.js';

describe('Security Advisor fixes in words', () => {
  afterEach(async () => { await setLanguage('en'); showToast.mockClear(); });

  it('shows the fix in German when the server said how, its own words otherwise', async () => {
    await setLanguage('de');
    api.post.mockResolvedValueOnce({ ok: true, message: 'AI search is off for kids and guests.', text: { msg_key: 'srv.sec_fixed_ai', params: {} } });
    await applySecurityFix('ai_search_family');
    expect(showToast).toHaveBeenCalledWith('Die KI-Suche ist für Kinder und Gäste ausgeschaltet.', 'success');
    api.post.mockResolvedValueOnce({ ok: true, message: 'Done.' });
    await applySecurityFix('other');
    expect(showToast).toHaveBeenLastCalledWith('Done.', 'success');
    api.post.mockResolvedValueOnce({});
    await applySecurityFix('other');
    expect(showToast.mock.calls.at(-1)[1]).toBe('success');
  });
});
