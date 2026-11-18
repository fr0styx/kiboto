/**
 * "Check that it works" on Power (SET-31, Power stage 3; report section 4, item 4): the battery test
 * and the practice run side by side, each with when it was last done and what came of it. They were
 * two buttons in the page header next to "Scan Hardware" and "Refresh", and the battery test's
 * answer vanished with its pop-up.
 */
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';
import { formatDateTime } from '../../format.js';
import { isAdministrator } from '../../admin-only.js';

const when = (ts) => formatDateTime(Number(ts) * (Number(ts) < 1e12 ? 1000 : 1));

/** The line under "Test the battery". */
export function batteryLine(s) {
  const last = s?.tests?.battery;
  if (!s?.can?.self_test)
    return t(
      'pwc.battery_cannot',
      'This UPS cannot be asked for a battery test from here: only a UPS reached over the network (NUT) takes the command. Most UPSs test their battery by themselves every few weeks.'
    );
  if (!last || !last.at)
    return t(
      'pwc.battery_never',
      'Not tested from Kiboto yet. The UPS runs on its battery for about 10 seconds; its result shows on the UPS itself.'
    );
  return t('pwc.battery_last', 'Last test sent on {when}. Its result shows on the UPS itself.', {
    when: when(last.at),
  });
}

/**
 * Draws the section into mount; the buttons press the page's existing handlers (they ask first).
 * @param {HTMLElement | null} mount
 * @param {any} s the /api/power answer
 */
export function renderPowerCheck(mount, s) {
  if (!mount) return;
  const show = Boolean(s) && !['none', 'unreadable', 'silent'].includes(s.state);
  mount.hidden = !show;
  if (!show) {
    mount.innerHTML = '<div id="ups-practice-line" class="ups-shutdown-line" hidden></div>';
    return;
  }
  // view-only people see the results; the buttons are for those who may change settings (SET-31)
  const admin = isAdministrator();
  const canTest = admin && Boolean(s.can?.self_test);
  mount.innerHTML = `
    <h3 class="pwc-title">${escapeHtml(t('pwc.title', 'Check that it works'))}</h3>
    <div class="pwc-item">
      <button type="button" class="btn-pill-toggle" id="pwc-battery"${canTest ? '' : ' disabled aria-describedby="pwc-battery-line"'}>${escapeHtml(t('pwc.battery', 'Test the battery'))}</button>
      <p class="pwc-line" id="pwc-battery-line">${escapeHtml(batteryLine(s))}</p>
    </div>
    <div class="pwc-item">
      <button type="button" class="btn-pill-toggle" id="pwc-practice"${admin && s.can?.practice ? '' : ' disabled'}>${escapeHtml(t('pwc.practice', 'Practice run'))}</button>
      <p class="pwc-line">${escapeHtml(t('pwc.practice_what', 'Kiboto acts as if the power went out for 15 seconds and checks who would switch the NAS off. Nothing is switched off.'))}</p>
      <div id="ups-practice-line" class="ups-shutdown-line" hidden></div>
    </div>${admin ? '' : `<p class="pwc-line">${escapeHtml(t('pwc.admins_only', 'Only administrators can run these.'))}</p>`}`;
  mount
    .querySelector('#pwc-battery')
    ?.addEventListener('click', () => document.getElementById('btn-run-ups-selftest')?.click());
  mount
    .querySelector('#pwc-practice')
    ?.addEventListener('click', () => document.getElementById('btn-ups-simulate')?.click());
}
