/**
 * Activity -> Right now (SET-27, Activity report section 4, tab 2): what the server is doing, in a
 * sentence, and the apps using it most. Drawn from the live stats the page already receives; it
 * redraws only while the tab is on screen.
 */
import { t } from '../i18n.js';
import { formatFixed } from '../format.js';
import { ZettEventBus } from '../event-bus.js';
import { state } from '../state.js';

const BUSY_PCT = 25;

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
    else if (!asleep) out.push(t('now.drives_awake', '{n, plural, one {The drive is awake.} other {All # drives are awake.}}', { n: awake }));
    else out.push(t('now.drives_some', '{awake} awake, {asleep} asleep.', { awake: t('now.n_drives', '{n, plural, one {# drive} other {# drives}}', { n: awake }), asleep }));
  }
  return out;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function renderRightNow(mount = document.getElementById('right-now'), stats = state.latestStats) {
  if (!mount) return false;
  const head = el('p', 'right-now-line', rightNowSentences(stats).join(' '));
  const apps = topApps(stats && stats.docker);
  const parts = [head];
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
  mount.replaceChildren(...parts);
  mount.hidden = false;
  return true;
}

let _listening = false;

/** Draws Right now and keeps it current while it is on screen. */
export function installRightNow(mount = document.getElementById('right-now')) {
  if (!mount) return false;
  renderRightNow(mount);
  if (!_listening) {
    _listening = true;
    ZettEventBus.on('stats:updated', (stats) => {
      const m = document.getElementById('right-now');
      if (m && m.offsetParent !== null) renderRightNow(m, stats);
    });
  }
  return true;
}
