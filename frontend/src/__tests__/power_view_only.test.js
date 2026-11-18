// SET-31: someone who may only look at Power sees the answers, not buttons that answer "no permission".
import { describe, it, expect, vi } from 'vitest';

let scopes = ['hardware:read'];
vi.mock('../route-access.js', () => ({
  currentUser: () => ({ scopes }),
  hasScope: (have, want) => have.includes(want),
}));

const { renderPowerCheck } = await import('../components/management/power-check.js');
const { renderPowerSwitch } = await import('../components/management/power-switch.js');
const { renderPowerTop } = await import('../components/management/power-top.js');

describe('view-only Power', () => {
  it('greys the checks, hides Restart or shut down, and asks no question', async () => {
    document.body.innerHTML = '<section id="pc"></section><section id="ps"></section><div id="top"></div>';
    renderPowerCheck(document.getElementById('pc'), {
      state: 'protected',
      can: { self_test: true, practice: true },
      tests: {},
    });
    expect(/** @type {HTMLButtonElement} */ (document.getElementById('pwc-battery')).disabled).toBe(true);
    expect(/** @type {HTMLButtonElement} */ (document.getElementById('pwc-practice')).disabled).toBe(true);
    expect(document.getElementById('pc')?.textContent).toContain('Only administrators can run these.');
    const ps = /** @type {HTMLElement} */ (document.getElementById('ps'));
    await renderPowerSwitch(ps);
    expect(ps.hidden).toBe(true);
    renderPowerTop(document.getElementById('top'), {
      state: 'protected',
      numbers: {},
      switch_off: { by: 'kiboto', ok: true },
      rule: {},
      checks: [],
      comes_back: { answer: 'ask', at: 1762900000 },
    });
    expect(document.querySelector('[data-back]')).toBeNull();
  });

  it('an administrator gets the buttons', () => {
    scopes = ['system:config', 'system:power'];
    document.body.innerHTML = '<section id="pc"></section>';
    renderPowerCheck(document.getElementById('pc'), {
      state: 'protected',
      can: { self_test: true, practice: true },
      tests: {},
    });
    expect(/** @type {HTMLButtonElement} */ (document.getElementById('pwc-battery')).disabled).toBe(false);
  });
});
