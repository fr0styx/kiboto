// SET-31, Power stage 3: "Check that it works", the battery test and the practice run with their last results.
import { describe, it, expect, vi } from 'vitest';
import { batteryLine, renderPowerCheck } from '../components/management/power-check.js';

describe('check that it works', () => {
  it('says what the battery test can do and when it was last sent', () => {
    expect(batteryLine({ can: { self_test: false } })).toMatch(
      /^This UPS cannot be asked for a battery test from here/
    );
    expect(batteryLine({ can: { self_test: true }, tests: {} })).toMatch(/^Not tested from Kiboto yet/);
    expect(batteryLine({ can: { self_test: true }, tests: { battery: { at: 1762900000 } } })).toMatch(
      /^Last test sent on .+\. Its result shows on the UPS itself\.$/
    );
  });

  it('is shown with a UPS, greys the battery test where it cannot be sent, and presses the existing handlers', () => {
    document.body.innerHTML =
      '<section id="pc" hidden></section><button id="btn-run-ups-selftest"></button><button id="btn-ups-simulate"></button>';
    const mount = /** @type {HTMLElement} */ (document.getElementById('pc'));
    const test = vi.fn();
    const practice = vi.fn();
    document.getElementById('btn-run-ups-selftest')?.addEventListener('click', test);
    document.getElementById('btn-ups-simulate')?.addEventListener('click', practice);
    renderPowerCheck(mount, { state: 'protected', can: { self_test: true, practice: true }, tests: {} });
    expect(mount.hidden).toBe(false);
    /** @type {HTMLElement} */ (mount.querySelector('#pwc-battery')).click();
    /** @type {HTMLElement} */ (mount.querySelector('#pwc-practice')).click();
    expect(test).toHaveBeenCalledTimes(1);
    expect(practice).toHaveBeenCalledTimes(1);
    expect(mount.querySelector('#ups-practice-line')).not.toBeNull();
    renderPowerCheck(mount, { state: 'protected', can: { self_test: false, practice: true }, tests: {} });
    expect(/** @type {HTMLButtonElement} */ (mount.querySelector('#pwc-battery')).disabled).toBe(true);
    renderPowerCheck(mount, { state: 'none' });
    expect(mount.hidden).toBe(true);
    expect(mount.querySelector('#ups-practice-line')).not.toBeNull(); // the practice answer still has its place
    renderPowerCheck(null, { state: 'protected' });
  });
});
