// Re-audit R2: the speed between this device and the NAS, in words.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import {
  speedVerdict,
  speedText,
  runSpeedTest,
  measureDelay,
  measureUpload,
  measureDownload,
} from '../components/management/speed-test.js';
import { setLanguage } from '../i18n.js';

describe('speed test', () => {
  afterEach(async () => {
    vi.restoreAllMocks();
    await setLanguage('en');
    document.body.innerHTML = '';
  });

  it('says what a speed means', () => {
    expect(speedVerdict(940)).toMatch(/^Fast/);
    expect(speedVerdict(300)).toMatch(/^Good/);
    expect(speedVerdict(60)).toMatch(/^Fine/);
    expect(speedVerdict(8)).toMatch(/^Slow/);
    expect(speedText(940.4)).toBe('940 Mbit/s');
    expect(speedText(8.26)).toBe('8.3 Mbit/s');
  });

  it('shows each step, then both directions, the answer time and the verdict of the slower one', async () => {
    document.body.innerHTML = '<button id="btn-speed-test"></button><div id="net-speed-result"></div>';
    const box = document.getElementById('net-speed-result');
    const steps = [];
    const seen = (v) => async () => {
      steps.push(box.textContent);
      expect(document.getElementById('btn-speed-test').disabled).toBe(true);
      return v;
    };
    const out = await runSpeedTest(box, { delay: seen(2.4), down: seen(940), up: seen(88) });
    expect(steps).toEqual(['Timing the answer…', 'Fetching from the NAS…', 'Sending to the NAS…']);
    expect(out).toEqual({ down: 940, up: 88, delay: 2.4 });
    expect(box.textContent).toContain('940 Mbit/s');
    expect(box.textContent).toContain('88 Mbit/s');
    expect(box.textContent).toContain('2.4 ms');
    expect(box.querySelector('p').textContent).toMatch(/^Fine/); // the slower direction decides
    expect(document.getElementById('btn-speed-test').disabled).toBe(false);
  });

  it('says so when it cannot measure, in the reader language, and works without the button', async () => {
    await setLanguage('de');
    document.body.innerHTML = '<div id="net-speed-result"></div>';
    const box = document.getElementById('net-speed-result');
    const out = await runSpeedTest(box, {
      delay: async () => {
        throw new Error('offline');
      },
    });
    expect(out).toBeNull();
    expect(box.textContent).toContain('offline');
    expect(box.textContent).toContain('Geschwindigkeit');
    expect(await runSpeedTest(null)).toBeNull();
  });

  it('times five small requests and takes the middle one', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ time: 1 });
    const ticks = [0, 9, 9, 11, 11, 14, 14, 15, 15, 45]; // 9, 2, 3, 1, 30 ms
    expect(await measureDelay(() => ticks.shift())).toBe(3);
    expect(get).toHaveBeenCalledTimes(5);
  });

  it('sends pieces until the time is up and counts what the NAS received', async () => {
    const post = vi
      .spyOn(api, 'postRaw')
      .mockResolvedValue(/** @type {any} */ ({ json: async () => ({ bytes: 2 * 1024 * 1024 }) }));
    const ticks = [0, 500, 1000, 1000]; // start, after piece 1, after piece 2 (limit reached), end
    const mbit = await measureUpload(() => ticks.shift(), 1000);
    expect(post).toHaveBeenCalledTimes(2);
    expect(Math.round(mbit)).toBe(34); // 4 MiB in one second
  });

  it('reads until the time is up, then stops the transfer', async () => {
    const pieces = [new Uint8Array(1_000_000), new Uint8Array(1_000_000), new Uint8Array(1_000_000)];
    let aborted = false;
    const fetcher = async (_url, opts) => {
      opts.signal.addEventListener('abort', () => {
        aborted = true;
      });
      return /** @type {any} */ ({
        body: { getReader: () => ({ read: async () => ({ done: pieces.length === 0, value: pieces.shift() }) }) },
      });
    };
    const ticks = [0, 400, 1000, 1000];
    const mbit = await measureDownload(() => ticks.shift(), 1000, fetcher);
    expect(aborted).toBe(true);
    expect(Math.round(mbit)).toBe(16); // 2 MB in one second
    // a short answer ends by itself
    pieces.length = 0;
    pieces.push(new Uint8Array(500_000));
    const short = [0, 100, 250];
    expect(Math.round(await measureDownload(() => short.shift(), 1000, fetcher))).toBe(16);
  });

  it('the button on the Network page starts it, on a NAS without Tailscale too', async () => {
    document.body.innerHTML = '<button id="btn-speed-test"></button><div id="net-speed-result"></div>';
    vi.spyOn(api, 'get').mockRejectedValue(new Error('offline'));
    const { initNetworkControls } = await import('../components/management/network.js');
    initNetworkControls();
    initNetworkControls(); // bound once
    document.getElementById('btn-speed-test').click();
    await vi.waitFor(() => expect(document.getElementById('net-speed-result').textContent).toContain('offline'));
  });
});
