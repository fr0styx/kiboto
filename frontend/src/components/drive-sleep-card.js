/**
 * Let hard drives sleep (off by default) on the Power page, only where Kiboto is the machine's
 * system: elsewhere the host's own spin-down setting decides and the card stays hidden.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';

/** "20 minutes", "1 hour", "2 hours". */
export function duration(minutes) {
  if (minutes < 60) return t('hdsleep.n_min', '{n, plural, one {# minute} other {# minutes}}', { n: minutes });
  if (minutes === 60) return t('hdsleep.one_hour', '1 hour');
  return t('hdsleep.n_hours', '{n, plural, one {# hour} other {# hours}}', { n: minutes / 60 });
}

/** "Off", "After 20 minutes". */
export function sleepLabel(minutes) {
  return minutes ? t('hdsleep.after', 'After {time}', { time: duration(minutes) }) : t('hdsleep.off', 'Off');
}

/** The status line: the setting, then any drive that was asleep or refused. */
export function sleepStatus(st) {
  if (!st || !st.minutes) return t('hdsleep.st_off', 'Off: the drives keep spinning.');
  const rows = st.last || [];
  const base = t('hdsleep.st_on', 'Spinning drives sleep after {time} with nothing to do.', {
    time: duration(st.minutes),
  });
  const failed = rows.filter((r) => r.state === 'failed').map((r) => r.drive);
  const asleep = rows.filter((r) => r.state === 'asleep').map((r) => r.drive);
  const parts = [base];
  if (!rows.length) parts.push(t('hdsleep.none', 'No spinning data drives were found.'));
  if (failed.length)
    parts.push(t('hdsleep.failed', 'These drives refused the timer: {list}.', { list: failed.join(', ') }));
  if (asleep.length)
    parts.push(t('hdsleep.asleep', 'Asleep, so left alone until the next start: {list}.', { list: asleep.join(', ') }));
  return parts.join(' ');
}

function html(st) {
  const opts = st.choices
    .map((m) => `<option value="${m}"${m === st.minutes ? ' selected' : ''}>${escapeHtml(sleepLabel(m))}</option>`)
    .join('');
  return `
    <div class="fw-head">
      <div>
        <h3 class="account-h" id="ds-title">${escapeHtml(t('hdsleep.title', 'Let hard drives sleep'))}</h3>
        <p class="fw-status" id="ds-status" aria-live="polite">${escapeHtml(sleepStatus(st))}</p>
      </div>
    </div>
    <p class="fw-why">${escapeHtml(
      t(
        'hdsleep.help',
        'A spinning drive with nothing to do stops after this long and starts again the moment it is needed, which takes a few seconds. Saves power and noise; the system disk and USB drives are left out.'
      )
    )}</p>
    <label class="ddns-field"><span>${escapeHtml(t('hdsleep.label', 'Sleep after'))}</span><select id="ds-minutes">${opts}</select></label>
    <div class="fw-error" id="ds-error" role="alert" hidden></div>`;
}

export async function renderDriveSleepCard(mount = document.getElementById('drive-sleep-card')) {
  if (!mount) return null;
  let st;
  try {
    st = await api.get('/api/system/drive-sleep');
  } catch {
    mount.hidden = true;
    return null;
  }
  if (!st.applies) {
    mount.hidden = true;
    return st;
  }
  mount.innerHTML = html(st);
  mount.hidden = false;
  const err = /** @type {HTMLElement} */ (mount.querySelector('#ds-error'));
  const pick = /** @type {HTMLSelectElement} */ (mount.querySelector('#ds-minutes'));
  pick.addEventListener('change', async () => {
    err.hidden = true;
    try {
      await api.put('/api/system/drive-sleep', { minutes: Number(pick.value) });
      await renderDriveSleepCard(mount);
    } catch (e) {
      err.textContent = e instanceof Error ? e.message : String(e);
      err.hidden = false;
    }
  });
  return st;
}
