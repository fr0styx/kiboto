/**
 * Cooling in plain words (Hardware 2, the status sentence): the Hardware page's "Now" list and the
 * Overview's Cooling tile, read from the live readings the fans already use (no drive is asked).
 * Each row says its state with a word as well as a colour.
 */
import { formatNumber } from '../format.js';
import { t } from '../i18n.js';
import { modeName } from './fan-modes.js';

const FULL_PWM = 183; // backend/config.py FAN_MAX_PWM
// [warm, too hot] in °C; too hot is where Kiboto runs the fans at full speed (drives: the safety
// floor, backend/hardware/fans.py FLOOR_START_C and FLOOR_FULL_C)
const LIMITS = { cpu: [70, 80], hdd: [45, 52], nvme: [60, 75] };
const ORDER = { ok: 0, warm: 1, hot: 2 };

function levelOf(temp, [warm, hot]) {
  if (temp >= hot) return 'hot';
  return temp >= warm ? 'warm' : 'ok';
}

function word(level) {
  if (level === 'hot') return t('hw.st_hot', 'too hot');
  return level === 'warm' ? t('hw.st_warm', 'running warm') : t('hw.st_fine', 'fine');
}

function tempRow(id, label, temp, limits) {
  const level = levelOf(temp, limits);
  return {
    id,
    label,
    level,
    value: t('hw.st_temp', '{temp} °C · {word}', { temp: Math.round(temp), word: word(level) }),
  };
}

/** The hard drives that are awake (with a reading, and without one), and whether there are any. */
function spinning(stats) {
  const hdd = (stats?.disks || []).filter((d) => String(d.dev || '').startsWith('sd'));
  const up = hdd.filter((d) => !d.standby);
  return {
    hdd,
    awake: up.filter((d) => typeof d.temp === 'number'),
    unread: up.filter((d) => typeof d.temp !== 'number'),
  };
}

/**
 * The rows of the Hardware page's "Now" list and the worst level among them, or null without
 * readings. Fans at full speed name what is hot; stopped fans say the drives sleep.
 */
export function coolingStatus(stats) {
  if (!stats) return null;
  const fc = stats.fan_control || {};
  const rows = [];
  const cpu = stats.cpu?.temp;
  if (typeof cpu === 'number') rows.push(tempRow('cpu', t('hw.st_cpu', 'Processor'), cpu, LIMITS.cpu));
  const { hdd, awake, unread } = spinning(stats);
  if (awake.length) {
    const hottest = Math.max(...awake.map((d) => d.temp));
    const row = tempRow('drives', t('hw.st_drives', 'Drives'), hottest, LIMITS.hdd);
    if (unread.length) {
      // a spinning drive without a reading counts as hot after 3 minutes (fan_control._floor_temp)
      row.value = t('hw.st_temp_unread', '{temp} °C · {word} · {n} without a reading', {
        temp: Math.round(hottest),
        word: word(row.level),
        n: unread.length,
      });
      if (row.level === 'ok') row.level = 'warm';
    }
    rows.push(row);
  } else if (unread.length) {
    rows.push({
      id: 'drives',
      label: t('hw.st_drives', 'Drives'),
      level: 'warm',
      value: t('hw.st_unread', 'no temperature reading'),
    });
  } else if (hdd.length) {
    rows.push({ id: 'drives', label: t('hw.st_drives', 'Drives'), level: 'ok', value: t('hw.st_asleep', 'asleep') });
  }
  if (typeof fc.nvme_temp === 'number')
    rows.push(tempRow('nvme', t('hw.st_nvme', 'Fast drives (NVMe)'), fc.nvme_temp, LIMITS.nvme));
  const pwm = fc.zone1_pwm;
  if (typeof pwm === 'number' && fc.driver_mode && fc.driver_mode !== 'none') {
    const rpm = Array.isArray(stats.fans) ? Number(stats.fans[0]) || 0 : 0;
    const hot = rows.find((r) => r.level === 'hot' && r.id !== 'fans');
    let value;
    if (pwm === 0) value = t('hw.st_fans_stopped', 'stopped while the drives sleep');
    else if (pwm >= FULL_PWM && hot)
      value = t('hw.st_fans_full', 'full speed: {what} is hot', {
        what: hot.id === 'cpu' ? t('hw.st_what_cpu', 'the processor') : t('hw.st_what_drive', 'a drive'),
      });
    else if (pwm >= FULL_PWM && unread.length)
      value = t('hw.st_fans_unread', "full speed: a drive's temperature can't be read");
    else
      value = t('hw.st_fans_speed', '{pct} % · {rpm} rpm', {
        pct: Math.round((pwm / FULL_PWM) * 100),
        rpm: formatNumber(rpm),
      });
    rows.push({ id: 'fans', label: t('hw.st_fans', 'Fans'), level: pwm >= FULL_PWM && hot ? 'hot' : 'ok', value });
  }
  if (!rows.length) return null;
  const level = rows.reduce((worst, r) => (ORDER[r.level] > ORDER[worst] ? r.level : worst), 'ok');
  return { rows, level };
}

/** The Overview's Cooling tile: "Balanced · 38 °C", or that the drives sleep; '' without fan control. */
export function coolingLine(stats) {
  const fc = stats?.fan_control;
  if (!fc || !fc.driver_mode || fc.driver_mode === 'none') return '';
  const mode = modeName(fc.profile, fc.manual_pct);
  const { hdd, awake } = spinning(stats);
  if (awake.length)
    return t('ov.tile_cooling_line', '{mode} · {temp} °C', {
      mode,
      temp: Math.round(Math.max(...awake.map((d) => d.temp))),
    });
  return hdd.length ? t('ov.tile_cooling_asleep', '{mode} · drives asleep', { mode }) : mode;
}

/** Draws the "Now" list on the Hardware page. */
export function renderCoolingStatus(stats, doc = document) {
  const list = doc.getElementById('hw-status-rows');
  const box = doc.getElementById('hw-status');
  const status = coolingStatus(stats);
  if (!list || !box) return;
  box.hidden = !status;
  if (!status) return;
  box.dataset.level = status.level;
  list.replaceChildren(
    ...status.rows.map((r) => {
      const li = doc.createElement('li');
      li.dataset.level = r.level;
      const dot = doc.createElement('span');
      dot.className = 'hw-st-dot';
      dot.setAttribute('aria-hidden', 'true');
      const label = doc.createElement('span');
      label.className = 'hw-st-label';
      label.textContent = r.label;
      const value = doc.createElement('strong');
      value.textContent = r.value;
      li.append(dot, label, value);
      return li;
    })
  );
}
