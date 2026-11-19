// Network: the speed between this device and the NAS (re-audit R2). The browser fetches random
// bytes, sends some back and times a few small requests; nothing leaves the connection in use.
import { request, api } from '../../api.js';
import { t } from '../../i18n.js';
import { formatFixed } from '../../format.js';

const MBIT = 1_000_000;
export const LIMIT_MS = 4000; // each direction runs this long at most
const UPLOAD_PIECE = 2 * 1024 * 1024; // well under the server's smallest body limit

/** What the slower direction means, in words. */
export function speedVerdict(mbit) {
  if (mbit >= 700) return t('net.speed_fast', 'Fast: a full gigabit connection or better.');
  if (mbit >= 200) return t('net.speed_good', 'Good: big copies move quickly and 4K video plays without waiting.');
  if (mbit >= 30) return t('net.speed_fine', 'Fine for photos, documents and HD video. Big copies take a while.');
  return t(
    'net.speed_slow',
    'Slow. On Wi-Fi, move closer to the router or use a cable; away from home, your internet connection sets the limit.'
  );
}

export function speedText(mbit) {
  return t('net.speed_mbit', '{value} Mbit/s', { value: formatFixed(mbit, mbit < 10 ? 1 : 0) });
}

const median = (list) => [...list].sort((a, b) => a - b)[Math.floor(list.length / 2)];

/** The delay of a small request, the middle one of five. */
export async function measureDelay(now = () => performance.now()) {
  const times = [];
  for (let i = 0; i < 5; i++) {
    const started = now();
    await api.get('/api/network/speedtest/ping');
    times.push(now() - started);
  }
  return median(times);
}

/** Megabits per second arriving from the NAS: reads until the limit, then stops the transfer. */
export async function measureDownload(now = () => performance.now(), limitMs = LIMIT_MS, fetcher = request) {
  const stop = new AbortController();
  const started = now();
  const res = await fetcher('/api/network/speedtest/download?mb=200', { method: 'GET', signal: stop.signal });
  const reader = res.body.getReader();
  let bytes = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    bytes += value.length;
    if (now() - started >= limitMs) {
      stop.abort();
      break;
    }
  }
  return (bytes * 8) / MBIT / Math.max((now() - started) / 1000, 0.001);
}

/** Megabits per second going to the NAS: pieces of 2 MB until the limit. */
export async function measureUpload(now = () => performance.now(), limitMs = LIMIT_MS) {
  const piece = new Blob([new Uint8Array(UPLOAD_PIECE)]);
  const started = now();
  let bytes = 0;
  do {
    const res = await api.postRaw('/api/network/speedtest/upload', piece, {
      headers: { 'Content-Type': 'application/octet-stream' },
    });
    bytes += (await res.json()).bytes || 0;
  } while (now() - started < limitMs && bytes < 400 * UPLOAD_PIECE);
  return (bytes * 8) / MBIT / Math.max((now() - started) / 1000, 0.001);
}

export function resultHtml({ down, up, delay }) {
  const row = (label, value) => {
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.textContent = value;
    return [dt, dd];
  };
  const dl = document.createElement('dl');
  dl.className = 'net-dl';
  dl.append(
    ...row(t('net.speed_down', 'From the NAS to this device'), speedText(down)),
    ...row(t('net.speed_up', 'From this device to the NAS'), speedText(up)),
    ...row(
      t('net.speed_delay', 'Answer time'),
      t('net.speed_ms', '{value} ms', { value: formatFixed(delay, delay < 10 ? 1 : 0) })
    )
  );
  const verdict = document.createElement('p');
  verdict.className = 'net-home-line';
  verdict.textContent = speedVerdict(Math.min(down, up));
  return [verdict, dl];
}

let running = false;

/** Runs the three measurements and writes each step into the result box. */
export async function runSpeedTest(box = document.getElementById('net-speed-result'), measure = {}) {
  if (!box || running) return null;
  running = true;
  const button = document.getElementById('btn-speed-test');
  if (button) button.disabled = true;
  const say = (text) => {
    box.textContent = text;
  };
  try {
    say(t('net.speed_step_delay', 'Timing the answer…'));
    const delay = await (measure.delay || measureDelay)();
    say(t('net.speed_step_down', 'Fetching from the NAS…'));
    const down = await (measure.down || measureDownload)();
    say(t('net.speed_step_up', 'Sending to the NAS…'));
    const up = await (measure.up || measureUpload)();
    box.replaceChildren(...resultHtml({ down, up, delay }));
    return { down, up, delay };
  } catch (e) {
    say(t('net.speed_failed', "The speed couldn't be measured: {error}", { error: e?.message || '' }));
    return null;
  } finally {
    running = false;
    if (button) button.disabled = false;
  }
}
