// After signing in, the page says when and from what the account was last signed in.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { showToast } from '../toast.js';
import { lastSignInText, sayLastSignIn } from '../components/last-signin.js';
import { setLanguage } from '../i18n.js';

vi.mock('../toast.js', async (orig) => ({ ...(await orig()), showToast: vi.fn() }));

const UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 Version/19.0 Mobile/15E148 Safari/604.1';

describe('last sign-in notice', () => {
  afterEach(async () => {
    vi.mocked(showToast).mockClear();
    await setLanguage('en');
  });

  it('says when and from which device', () => {
    const text = lastSignInText({ at: 1763500000, ip: '192.168.1.30', user_agent: UA });
    expect(text).toMatch(/^Last sign-in: .+, Safari on iPhone\.$/);
    const plain = lastSignInText({ at: 1763500000, user_agent: '' });
    expect(plain).toMatch(/^Last sign-in: .+\.$/);
    expect(plain).not.toContain(' on ');
  });

  it('says nothing on the first sign-in', () => {
    expect(lastSignInText(null)).toBe('');
    expect(lastSignInText({ at: 0 })).toBe('');
    expect(sayLastSignIn(undefined)).toBe(false);
    expect(showToast).not.toHaveBeenCalled();
  });

  it('shows it as a note, in the reader language', async () => {
    await setLanguage('de');
    expect(sayLastSignIn({ at: 1763500000, user_agent: UA })).toBe(true);
    expect(showToast).toHaveBeenCalledWith(
      expect.stringMatching(/^Letzte Anmeldung: .+ Safari unter iPhone\.$/),
      'info'
    );
  });
});
