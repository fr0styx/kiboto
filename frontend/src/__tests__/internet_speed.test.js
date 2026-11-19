// Network: "Test the internet line" (owner, 19 Nov 2026).
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { showInternetSpeed, internetResultNodes } from '../components/management/internet-speed.js';
import { WORDS } from '../components/management/outside-checks.js';

const LAST = { down_mbit: 250.4, up_mbit: 40, answer_ms: 12.4, measured_at: 1763500000 };

describe('internet speed test', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('says where to turn it on while it is off, and asks nothing', async () => {
    document.body.innerHTML = '<div id="net-internet-speed"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({ enabled: false, last: null });
    const post = vi.spyOn(api, 'post');
    await showInternetSpeed();
    const box = document.getElementById('net-internet-speed');
    expect(box.querySelector('button')).toBeNull();
    expect(box.textContent).toContain('Security → Checks that use the internet');
    expect(post).not.toHaveBeenCalled();
  });

  it('shows the last result and measures again on the button', async () => {
    document.body.innerHTML = '<div id="net-internet-speed"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({ enabled: true, last: LAST });
    let finish;
    const post = vi.spyOn(api, 'post').mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    await showInternetSpeed();
    const box = document.getElementById('net-internet-speed');
    expect(box.textContent).toContain('250 Mbit/s');
    expect(box.textContent).toContain('40 Mbit/s');
    expect(box.textContent).toContain('12 ms');
    const button = box.querySelector('button');
    button.click();
    expect(button.disabled).toBe(true);
    expect(box.textContent).toContain('Measuring the internet line');
    finish({ ...LAST, down_mbit: 500 });
    await vi.waitFor(() => expect(box.textContent).toContain('500 Mbit/s'));
    expect(post).toHaveBeenCalledWith('/api/network/speedtest/internet', {});
    expect(button.disabled).toBe(false);
  });

  it('says why when the line cannot be measured', async () => {
    document.body.innerHTML = '<div id="net-internet-speed"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({ enabled: true, last: null });
    vi.spyOn(api, 'post').mockRejectedValue(new Error('no route to host'));
    await showInternetSpeed();
    const box = document.getElementById('net-internet-speed');
    expect(box.querySelector('dl')).toBeNull(); // never measured: no numbers
    box.querySelector('button').click();
    await vi.waitFor(() => expect(box.textContent).toContain("couldn't be measured: no route to host"));
  });

  it('hides for someone who may not see it, needs its box, and has its switch on the Security page', async () => {
    expect(await showInternetSpeed(null)).toBeNull();
    document.body.innerHTML = '<div id="net-internet-speed"></div>';
    vi.spyOn(api, 'get').mockRejectedValue(new Error('403'));
    expect(await showInternetSpeed()).toBeNull();
    expect(document.getElementById('net-internet-speed').hidden).toBe(true);
    expect(internetResultNodes(null)).toEqual([]);
    expect(internetResultNodes({})[0].textContent).toContain('0 Mbit/s');
    const [title, desc] = WORDS.internet_speed();
    expect(title).toBe('Test the internet line');
    expect(desc).toContain('Cloudflare');
  });
});
