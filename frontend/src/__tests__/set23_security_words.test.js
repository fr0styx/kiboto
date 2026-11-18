import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { setLanguage } from '../i18n.js';
import { checkVerdict, checkDetails, fetchAndRenderSecurityPosture } from '../components/management/security.js';

afterEach(async () => {
  vi.restoreAllMocks();
  await setLanguage('en');
});

const ok = { id: 'https_transport', passed: true, penalty: 0, severity: 'info' };
const tip = { id: 'sec_default_admin', passed: false, penalty: 0, severity: 'low' };
const look = { id: 'admin_mfa', passed: false, penalty: 15, severity: 'high' };
const crit = { id: 'smb_guest_access', passed: false, penalty: 20, severity: 'critical' };

describe('the security check in words, no score (SET-23, Settings decision 4)', () => {
  it('says how many things need a look, or that everything is fine', () => {
    expect(checkVerdict([ok, tip, look])).toEqual(['1 thing needs a look', 'warn']);
    expect(checkVerdict([look, crit])).toEqual(['2 things need a look', 'bad']);
    expect(checkVerdict([ok, tip])).toEqual(['Everything is fine · 1 suggestion', 'ok']);
    expect(checkVerdict([ok])).toEqual(['Everything is fine', 'ok']);
    expect(checkVerdict()).toEqual(['Everything is fine', 'ok']);
  });

  it('plain HTTP at home has its own sentence', () => {
    expect(
      checkDetails({ id: 'https_transport', passed: false, variant: 'home', params: { outside: false }, details: 'x' })
    ).toContain('fine at home');
  });

  it('the page shows the words, no score, and what needs a look comes first', async () => {
    document.body.innerHTML = '<span id="sec-advisor-score-badge"></span><div id="sec-advisor-items"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({ score: 65, grade: 'C', checks: [ok, tip, look] });
    await fetchAndRenderSecurityPosture();
    const badge = /** @type {HTMLElement} */ (document.getElementById('sec-advisor-score-badge'));
    expect(badge.textContent).toBe('1 thing needs a look');
    expect(badge.dataset.tone).toBe('warn');
    expect(badge.textContent).not.toMatch(/Score|grade|\/100/);
    const ids = [...document.querySelectorAll('.sec-advisor-item')].map(
      (e) => /** @type {HTMLElement} */ (e).dataset.checkId
    );
    expect(ids).toEqual(['admin_mfa', 'sec_default_admin', 'https_transport']);
    const tipLine = /** @type {HTMLElement} */ (
      document.querySelector('[data-check-id="sec_default_admin"] div div div:last-child')
    );
    expect(tipLine.style.color).toBe('var(--kb-text-muted)'); // a suggestion is not red
    await setLanguage('de');
    await fetchAndRenderSecurityPosture();
    expect(badge.textContent).toBe('1 Sache bitte prüfen');
  });
});
