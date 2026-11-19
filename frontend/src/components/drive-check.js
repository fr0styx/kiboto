/**
 * Drive Health: "Check this new drive" (owner's decision, 19 Nov 2026). For a drive that is not in
 * use yet: Kiboto reads its whole surface (hours), compares the drive's own counters before and
 * after, and says whether to trust it. Started by hand only; it only reads.
 */
import { api } from '../api.js';
import { showToast } from '../toast.js';
import { t } from '../i18n.js';
import { formatBytes, formatDateTime, formatUptime } from '../format.js';

const POLL_MS = 5000;
let _timer = null;

const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...kids.filter((k) => k !== null && k !== undefined && k !== ''));
  return node;
};

/** What a finished or broken-off check says about the drive. */
export function verdictSaid(run) {
  if (run.state === 'stopped')
    return t('dc.v_stopped', 'Stopped before the end. Nothing can be said about the drive yet.');
  if (run.state === 'too_hot')
    return t(
      'dc.v_too_hot',
      'It stopped itself: the drive reached {temp} °C. Let it cool, see to its airflow, and check it again.',
      {
        temp: run.why,
      }
    );
  if (run.state === 'failed')
    return t(
      'dc.v_failed',
      'The drive stopped answering ({why}). Do not trust it with data until a check runs to the end.',
      {
        why: run.why,
      }
    );
  if (run.verdict === 'bad')
    return t(
      'dc.v_bad',
      'Do not trust this drive with data: parts of it could not be read, or it reported damage while it was read. Send it back if you can.'
    );
  if (run.verdict === 'cable')
    return t(
      'dc.v_cable',
      'The drive read to the end, but data was damaged on the way to it. That is usually the cable or the bay: reseat the drive and check it again.'
    );
  return t('dc.v_good', 'This drive is good to use: every part of it was read without a problem.');
}

/** The numbers of a check: how much was read, how long it took, the slowest stretch, what could not be read. */
export function factsSaid(run) {
  const facts = [
    t('dc.f_read', 'Read {done} of {size}', {
      done: formatBytes(run.read_bytes || 0),
      size: formatBytes(run.size_bytes || 0),
    }),
  ];
  if (run.ended && run.started)
    facts.push(t('dc.f_took', 'took {time}', { time: formatUptime(Math.max(0, run.ended - run.started)) }));
  if (run.slowest_bps)
    facts.push(t('dc.f_slowest', 'slowest stretch {speed}/s', { speed: formatBytes(run.slowest_bps) }));
  facts.push(
    t(
      'dc.f_bad',
      '{count, plural, =0 {nothing unreadable} one {# place could not be read} other {# places could not be read}}',
      {
        count: run.unreadable || 0,
      }
    )
  );
  return facts.join(' · ');
}

/** "42 % · 180 MB/s · about 3h 10m left" while it reads. */
export function progressSaid(run) {
  const pct = run.size_bytes ? Math.floor(((run.read_bytes || 0) * 100) / run.size_bytes) : 0;
  const parts = [t('dc.p_pct', '{value} % read', { value: pct })];
  if (run.speed_bps) parts.push(`${formatBytes(run.speed_bps)}/s`);
  if (run.eta_secs) parts.push(t('dc.p_left', 'about {time} left', { time: formatUptime(run.eta_secs) }));
  return parts.join(' · ');
}

function stopLooking() {
  if (_timer) clearInterval(_timer);
  _timer = null;
}

function draw(box, drive) {
  const kids = [
    el('h4', { textContent: t('dc.title', 'Check this new drive') }),
    el('p', {
      className: 'dh-hint',
      textContent: t(
        'dc.hint',
        'For a drive that holds no data yet. Kiboto reads its whole surface, which takes hours, and compares what the drive says about itself before and after. Nothing is written to it. The drive stays awake until the check ends.'
      ),
    }),
  ];
  const run = drive.check;
  if (run) {
    const pct = run.size_bytes ? Math.floor(((run.read_bytes || 0) * 100) / run.size_bytes) : 0;
    const bar = el('progress', { max: 100, value: pct, className: 'dc-bar' });
    bar.setAttribute('aria-label', t('dc.title', 'Check this new drive'));
    const stop = el('button', {
      type: 'button',
      className: 'btn-pill-toggle',
      textContent: t('dc.stop', 'Stop the check'),
    });
    stop.dataset.dcAct = 'stop';
    kids.push(
      bar,
      el('p', { className: 'dh-hint', id: 'dc-progress', textContent: progressSaid(run) }),
      el('div', { className: 'dh-test-buttons' }, stop)
    );
  } else if (drive.free) {
    const start = el('button', {
      type: 'button',
      className: 'btn-pill-toggle is-primary',
      textContent: t('dc.start', 'Check this drive'),
    });
    start.dataset.dcAct = 'start';
    kids.push(el('div', { className: 'dh-test-buttons' }, start));
  }
  if (drive.last) {
    const last = drive.last;
    kids.push(
      el('p', {
        className: `dc-verdict is-${last.state === 'finished' ? last.verdict : 'unfinished'}`,
        textContent: verdictSaid(last),
      }),
      el('p', {
        className: 'dh-hint',
        textContent: `${t('dc.last', 'Last check {when}', { when: formatDateTime(last.ended || last.started) })}: ${factsSaid(last)}`,
      })
    );
  }
  box.replaceChildren(...kids);
  box.hidden = false;
}

/**
 * Draws the section for this drive: shown when the drive may be checked, is being checked, or has
 * a result. Returns true when it is shown.
 */
export async function mountDriveCheck(box, dev) {
  stopLooking();
  if (!box || !dev) return false;
  /** @type {any} */
  let drive = null;
  const load = async () => {
    const view = await api.get('/api/drives/check');
    drive = ((view && view.drives) || []).find((d) => d.dev === dev) || null;
    return drive;
  };
  try {
    await load();
  } catch {
    box.hidden = true;
    return false;
  }
  if (!drive || !(drive.free || drive.check || drive.last)) {
    box.hidden = true; // a drive in use, never checked: the section is not for it
    return false;
  }
  const again = async () => {
    if (!box.isConnected) return stopLooking();
    try {
      if (await load()) draw(box, drive);
    } catch {
      return; // the next look tries again
    }
    if (!drive || !drive.check) stopLooking(); // it ended: the result is on the page
  };
  const watch = () => {
    stopLooking();
    if (drive && drive.check) _timer = setInterval(again, POLL_MS);
  };
  draw(box, drive);
  watch();
  if (!box.dataset.bound) {
    box.dataset.bound = '1';
    box.addEventListener('click', async (e) => {
      const act = /** @type {HTMLElement} */ (e.target).dataset?.dcAct;
      if (!act) return;
      const path = `/api/drives/${encodeURIComponent(box.dataset.dev || dev)}/check`;
      try {
        if (act === 'start') {
          await api.post(path, {});
          showToast(t('dc.started', 'The check has started. You can close this window; it goes on.'), 'success');
        } else {
          await api.post(`${path}/stop`, {});
          showToast(t('dc.stopping', 'Stopping the check.'), 'success');
        }
      } catch (err) {
        if (err?.error !== 'cancelled')
          showToast(t('dc.failed', "That didn't work: {error}", { error: err?.message || '' }), 'error');
      }
      await again();
      watch();
    });
  }
  box.dataset.dev = dev;
  return true;
}

/** For tests: stop looking. */
export function resetDriveCheckForTesting() {
  stopLooking();
}
