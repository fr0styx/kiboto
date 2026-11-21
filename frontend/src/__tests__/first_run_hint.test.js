/** The sign-in page says where the first-time password is, while nobody has signed in yet. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { showFirstRunHint } from '../components/auth.js';
import { setLanguage } from '../i18n.js';

describe('the first-run hint on the sign-in page', () => {
  beforeEach(async () => {
    document.body.innerHTML = '<p id="login-first-run" hidden></p>';
    await setLanguage('en');
  });
  const answer = (body, ok = true) => vi.spyOn(window, 'fetch').mockResolvedValue({ ok, json: async () => body });

  it('points at the machine on a machine of its own', async () => {
    answer({ waiting: true, where: 'machine' });
    await showFirstRunHint();
    const line = document.getElementById('login-first-run');
    expect(line.hidden).toBe(false);
    expect(line.textContent).toContain("the code shown on this machine's screen");
  });

  it('points at the file elsewhere, in the reader language', async () => {
    await setLanguage('de');
    answer({ waiting: true, where: 'file' });
    await showFirstRunHint();
    expect(document.getElementById('login-first-run').textContent).toContain('initial-admin-password');
    expect(document.getElementById('login-first-run').textContent).toContain('Zum ersten Mal hier?');
    await setLanguage('en');
  });

  it('says nothing once someone has signed in, or when the server does not answer', async () => {
    answer({ waiting: false, where: 'machine' });
    await showFirstRunHint();
    expect(document.getElementById('login-first-run').hidden).toBe(true);
    answer({}, false);
    await showFirstRunHint();
    expect(document.getElementById('login-first-run').hidden).toBe(true);
    vi.spyOn(window, 'fetch').mockRejectedValue(new Error('offline'));
    await showFirstRunHint();
    expect(document.getElementById('login-first-run').hidden).toBe(true);
    document.body.innerHTML = '';
    await showFirstRunHint(); // no such line on the page: nothing to do
  });
});
