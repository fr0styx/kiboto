/**
 * Activity -> Right now (SET-27, Activity report section 4, tab 2): what the server is doing, in a
 * sentence, the jobs running and the apps using it most. Drawn from the live stats the page already
 * receives and /api/jobs (at most every 15 s); it redraws only while the tab is on screen.
 */
import { t } from '../i18n.js';
import { formatFixed } from '../format.js';
import { api } from '../api.js';
import { KibotoEventBus } from '../event-bus.js';
import { state } from '../state.js';

const BUSY_PCT = 25;
const JOBS_EVERY_MS = 15000;
let _jobs = [];
let _jobsAt = 0;

/** A job's title in the reader's language (as the Jobs list says it; copied, not imported, so this
 *  lazy module pulls no first-load code into its own chunk). */
function jobName(job) {
  return job.title_id ? t(job.title_id, job.title || '', job.title_params || {}) : job.title || '';
}

/** The jobs running or waiting, at most five, with the most advanced first. */
export function runningJobs(data, n = 5) {
  const active = data && Array.isArray(data.active) ? data.active : [];
  return active
    .filter((j) => j && (j.status === 'running' || j.status === 'queued' || j.status === 'paused'))
    .sort((a, b) => (b.percent ?? -1) - (a.percent ?? -1))
    .slice(0, n);
}

/** Fetches the running jobs when the last look is older than 15 s; a failure keeps the last list. */
export async function refreshJobs(now = Date.now()) {
  if (now - _jobsAt < JOBS_EVERY_MS) return _jobs;
  _jobsAt = now;
  try {
    _jobs = runningJobs(await api.get('/api/jobs'));
  } catch (_) {
    /* the Jobs list is not reachable: keep what was there */
  }
  return _jobs;
}

/** The apps using the processor most (Kiboto's own parts left out), at most five. */
export function topApps(docker, n = 5) {
  return (Array.isArray(docker) ? docker : [])
    .filter((c) => c && c.state === 'running' && !c.kiboto_own)
    .sort((a, b) => (b.cpu_pct || 0) - (a.cpu_pct || 0))
    .slice(0, n);
}

/** One sentence on the processor, then one on the drives. */
export function rightNowSentences(stats) {
  const s = stats || {};
  const cpu = Number(s.cpu && s.cpu.util) || 0;
  const apps = topApps(s.docker, 1);
  const out = [];
  if (cpu < BUSY_PCT) {
    out.push(t('now.quiet', 'Quiet.'));
  } else if (apps[0] && (apps[0].cpu_pct || 0) >= cpu / 2) {
    out.push(t('now.busy_app', 'The processor is busy: {app} is using most of it.', { app: apps[0].name }));
  } else {
    out.push(t('now.busy', 'The processor is busy ({pct}%).', { pct: Math.round(cpu) }));
  }
  const mem = Number(s.mem && s.mem.pct) || 0;
  if (mem >= 90) out.push(t('now.mem_full', 'Memory is nearly full.'));
  const disks = (Array.isArray(s.disks) ? s.disks : []).filter((d) => d && !d.is_nvme);
  if (disks.length) {
    const asleep = disks.filter((d) => d.standby).length;
    const awake = disks.length - asleep;
    if (!awake) out.push(t('now.drives_asleep', 'The drives are asleep.'));
    else if (!asleep)
      out.push(
        t('now.drives_awake', '{n, plural, one {The drive is awake.} other {All # drives are awake.}}', { n: awake })
      );
    else
      out.push(
        t('now.drives_some', '{awake} awake, {asleep} asleep.', {
          awake: t('now.n_drives', '{n, plural, one {# drive} other {# drives}}', { n: awake }),
          asleep,
        })
      );
  }
  return out;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function jobsBlock(jobs) {
  const box = el('div', 'right-now-jobs');
  box.append(
    el(
      'h4',
      'right-now-h',
      t('now.jobs_title', '{n, plural, one {# job running} other {# jobs running}}', { n: jobs.length })
    )
  );
  const list = el('ul', 'right-now-apps');
  for (const j of jobs) {
    const li = el('li');
    li.append(el('span', 'right-now-name', jobName(j)));
    const pct = typeof j.percent === 'number' ? `${formatFixed(Math.max(0, Math.min(100, j.percent)), 0)}%` : '';
    const what =
      j.status === 'queued'
        ? t('jobs.status_queued', 'Waiting')
        : j.status === 'paused'
          ? t('jobs.status_paused', 'Paused')
          : pct;
    li.append(el('span', 'right-now-use', what));
    list.append(li);
  }
  box.append(list);
  const open = /** @type {any} */ (globalThis).openJobsCentre;
  if (typeof open === 'function') {
    const btn = el('button', 'btn-secondary right-now-open', t('now.jobs_open', 'Open the Jobs list'));
    btn.setAttribute('type', 'button');
    btn.addEventListener('click', () => open());
    box.append(btn);
  }
  return box;
}

/** "Load (1, 5, 15 min): 0.52 · 0.48 · 0.40" in the reader's numbers; moved from Hardware (Hardware 3). */
export function loadLine(stats) {
  const l = stats && stats.cpu && stats.cpu.load_avg;
  if (!Array.isArray(l) || !l.length) return '';
  return t('now.load', 'Load (1, 5, 15 min): {load}', {
    load: l.map((v) => formatFixed(Number(v) || 0, 2)).join(' · '),
  });
}

export function renderRightNow(mount = document.getElementById('right-now'), stats = state.latestStats, jobs = _jobs) {
  if (!mount) return false;
  const head = el('p', 'right-now-line', rightNowSentences(stats).join(' '));
  const apps = topApps(stats && stats.docker);
  const parts = [head];
  if (jobs && jobs.length) parts.push(jobsBlock(jobs));
  if (apps.length) {
    parts.push(el('h4', 'right-now-h', t('now.apps_title', 'Apps by use')));
    const list = el('ol', 'right-now-apps');
    for (const c of apps) {
      const li = el('li');
      li.append(el('span', 'right-now-name', c.name));
      const mem = c.mem_used ? `${formatFixed(c.mem_used / (1024 * 1024), 0)} MB` : '';
      li.append(el('span', 'right-now-use', [`${formatFixed(c.cpu_pct || 0, 1)}%`, mem].filter(Boolean).join(' · ')));
      list.append(li);
    }
    parts.push(list);
  }
  const load = loadLine(stats);
  if (load) parts.push(el('p', 'right-now-load', load));
  mount.replaceChildren(...parts);
  mount.hidden = false;
  return true;
}

let _listening = false;

/** Draws Right now and keeps it current while it is on screen. */
export function installRightNow(mount = document.getElementById('right-now')) {
  if (!mount) return false;
  renderRightNow(mount);
  _jobsAt = 0;
  refreshJobs()
    .then(() => renderRightNow(mount))
    .catch(() => {});
  if (!_listening) {
    _listening = true;
    KibotoEventBus.on('stats:updated', (stats) => {
      const m = document.getElementById('right-now');
      if (!m || m.offsetParent === null) return;
      renderRightNow(m, stats);
      refreshJobs()
        .then((jobs) => renderRightNow(m, stats, jobs))
        .catch(() => {});
    });
  }
  return true;
}
