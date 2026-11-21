// New address settings for a machine of its own are a trial: keep them, go back, or the clock decides.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showActionToast: vi.fn(),
  showPromptToast: vi.fn(),
}));
const toast = await import('../toast.js');
const { api } = await import('../api.js');
const { showNetTrial, closeNetTrial, trialLine, linkElsewhere } = await import('../components/management/net-trial.js');
const { hostNote } = await import('../components/management/net-host.js');
const net = await import('../components/management/network.js');

const KEY = 'k'.repeat(32);
const flush = async () => {
  for (let i = 0; i < 6; i += 1) await Promise.resolve();
};
const el = (id) => /** @type {HTMLButtonElement} */ (document.getElementById(id));

beforeEach(() => {
  document.body.innerHTML = '<button id="opener">open</button>';
  vi.clearAllMocks();
});
afterEach(() => {
  closeNetTrial();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('the trial of new address settings', () => {
  it('names Debian as where the rest is set on a machine of its own', () => {
    expect(hostNote({ where: 'debian' })).toContain("Debian's own network settings on this machine");
  });

  it('only a link with the key, to another address, is offered to open', () => {
    expect(linkElsewhere(`http://192.168.1.50:8082/?keep-network=${KEY}`, '192.168.1.20')).toContain('192.168.1.50');
    expect(linkElsewhere(`http://192.168.1.50:8082/?keep-network=${KEY}`, '192.168.1.50')).toBe('');
    expect(linkElsewhere('http://192.168.1.50:8082', '192.168.1.20')).toBe(''); // no key: it would keep nothing
    expect(linkElsewhere(`javascript:alert(1)//keep-network=${KEY}`, 'x')).toBe('');
    expect(linkElsewhere(`http://:bad/?keep-network=${KEY}`, 'x')).toBe('');
    expect(linkElsewhere('', 'x')).toBe('');
    expect(linkElsewhere(undefined)).toBe('');
  });

  it('says what happens, with the seconds left', () => {
    expect(trialLine(42, false)).toBe(
      'If this page still works, keep the new settings. Otherwise this machine goes back to the settings from before in 42 seconds.'
    );
    expect(trialLine(42, true)).toContain('Open it there to keep the new settings');
    expect(trialLine(0, true)).toBe('This machine is back on the settings from before.');
  });

  it('keeps the new settings with the trial key and then reads the layout again', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok', kept: true });
    const after = vi.fn();
    const overlay = showNetTrial({ canary_id: KEY, timeout_sec: 60, url: '' }, after);
    expect(overlay?.getAttribute('role')).toBe('alertdialog');
    expect(el('net-trial-text').textContent).toContain('in 60 seconds');
    expect(document.getElementById('net-trial-link')).toBeNull();
    expect(showNetTrial({ seconds_left: 30 })).toBeNull(); // one trial, one dialog
    el('net-trial-keep').click();
    await flush();
    expect(post).toHaveBeenCalledWith('/api/network/host/confirm', { canary_id: KEY });
    expect(toast.showToast).toHaveBeenCalledWith('The new network settings are kept.', 'success');
    expect(document.getElementById('net-trial-overlay')).toBeNull();
    expect(after).toHaveBeenCalledTimes(1);
  });

  it('goes back at once when asked, and a page opened in the middle needs no key', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok', reverted: true });
    showNetTrial({ interface: 'enp1s0', seconds_left: 30, url: 'http://192.168.1.50:8082' });
    expect(el('net-trial-text').textContent).toContain('in 30 seconds');
    el('net-trial-back').click();
    await flush();
    expect(post).toHaveBeenCalledWith('/api/network/host/revert', { canary_id: null });
    expect(toast.showToast).toHaveBeenCalledWith('This machine is back on the settings from before.', 'success');
    expect(document.getElementById('net-trial-overlay')).toBeNull();
  });

  it('shows where Kiboto is moving to, and says when a button did not reach the machine', async () => {
    vi.spyOn(api, 'post').mockRejectedValue(new Error('Failed to fetch'));
    showNetTrial({ canary_id: KEY, timeout_sec: 60, url: `http://192.168.1.50:8082/?keep-network=${KEY}` });
    const link = /** @type {HTMLAnchorElement} */ (document.getElementById('net-trial-link'));
    expect(link.textContent).toBe('http://192.168.1.50:8082');
    expect(link.getAttribute('href')).toContain(`keep-network=${KEY}`);
    expect(el('net-trial-text').textContent).toContain('Kiboto is moving to a new address');
    el('net-trial-keep').click();
    await flush();
    expect(toast.showToast).toHaveBeenCalledWith(expect.stringContaining('did not reach this machine'), 'error');
    expect(document.getElementById('net-trial-overlay')).not.toBeNull(); // still deciding
  });

  it('counts down, and when the time is over only closing is left', () => {
    vi.useFakeTimers();
    const after = vi.fn();
    showNetTrial({ canary_id: KEY, timeout_sec: 3, url: '' }, after);
    vi.advanceTimersByTime(1000);
    expect(el('net-trial-text').textContent).toContain('in 2 seconds');
    vi.advanceTimersByTime(2500);
    expect(el('net-trial-text').textContent).toBe('This machine is back on the settings from before.');
    expect(el('net-trial-keep').hidden).toBe(true);
    expect(el('net-trial-back').textContent).toBe('Close');
    el('net-trial-back').click();
    expect(document.getElementById('net-trial-overlay')).toBeNull();
    expect(after).toHaveBeenCalledTimes(1);
  });

  it('a trial with no time left is shown as over', () => {
    showNetTrial({ seconds_left: 0 });
    expect(el('net-trial-text').textContent).toBe('This machine is back on the settings from before.');
    expect(el('net-trial-keep').hidden).toBe(true);
    closeNetTrial();
    showNetTrial(undefined);
    expect(el('net-trial-back').textContent).toBe('Close');
  });

  it('applying an address on a machine of its own opens the trial, once', async () => {
    document.body.innerHTML =
      '<input id="net-host-ip-input" value="192.168.1.50"><table><tbody id="network-physical-tbody"></tbody></table>';
    vi.spyOn(api, 'post').mockResolvedValue({ status: 'trial', canary_id: KEY, timeout_sec: 60, url: '' });
    vi.spyOn(api, 'get').mockResolvedValue({
      status: 'ok',
      summary: {},
      physical_interfaces: [],
      bonds: [],
      bridges: [],
      docker_networks: [],
      host: { managed: true, where: 'debian', can_change: { address: true }, trial: { seconds_left: 58 } },
    });
    await net.applyHostIpConfig();
    await net.fetchAndRenderNetworkTopology();
    await flush();
    await new Promise((r) => setTimeout(r, 0));
    expect(document.querySelectorAll('#net-trial-overlay')).toHaveLength(1);
    expect(toast.showToast).not.toHaveBeenCalledWith('Saved!', 'success');
  });
});
