/** Audit A13: the firewall card on the Security page. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api, ApiError } from '../api.js';
import { renderFirewallCard, whyNot, firewallStatus } from '../components/firewall-card.js';

const flush = () => new Promise((r) => setTimeout(r, 10));
const NONE = {
  web: false,
  ssh: false,
  smb: false,
  nfs: false,
  webdav: false,
  sftp: false,
  tailscale: false,
  apps: false,
};

describe('firewall card (audit A13)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('says why it cannot be managed here', () => {
    expect(whyNot('host')).toContain("the NAS's own firewall applies");
    expect(whyNot('no_nft')).toContain('nft tool is missing');
    expect(whyNot('no_cap')).toContain('NET_ADMIN');
    expect(whyNot('')).toBe('');
  });

  it('says what on and off mean', () => {
    expect(firewallStatus({ enabled: true })).toBe(
      'On: devices at home reach everything on this NAS. From outside your home, only what is ticked below.'
    );
    expect(firewallStatus({ enabled: false })).toBe(
      'Off: anything that can reach this NAS can reach every service on it.'
    );
    expect(firewallStatus(null)).toContain('Off:');
  });

  it('in a container: the reason shown, the switch and choices locked', async () => {
    document.body.innerHTML = '<section id="firewall-card" hidden></section>';
    vi.spyOn(api, 'get').mockResolvedValue({
      enabled: false,
      outside: NONE,
      possible: false,
      why_not: 'host',
      rules: 'table inet kiboto',
    });
    await renderFirewallCard();
    const box = /** @type {HTMLElement} */ (document.getElementById('firewall-card'));
    expect(box.hidden).toBe(false);
    expect(box.querySelector('#fw-status')?.textContent).toContain('Off: anything that can reach this NAS');
    expect(box.querySelector('#fw-why')?.textContent).toContain('Kiboto runs in a container');
    expect(/** @type {HTMLButtonElement} */ (box.querySelector('#fw-toggle')).disabled).toBe(true);
    expect(box.querySelectorAll('fieldset[disabled]').length).toBe(1);
    expect(box.querySelector('pre')?.textContent).toBe('table inet kiboto');
  });

  it('offers only what the outside may reach, nothing ticked at first, and no choice about home', async () => {
    document.body.innerHTML = '<section id="firewall-card" hidden></section>';
    vi.spyOn(api, 'get').mockResolvedValue({ enabled: true, outside: NONE, possible: true, why_not: '', rules: '' });
    await renderFirewallCard();
    const box = /** @type {HTMLElement} */ (document.getElementById('firewall-card'));
    expect(box.querySelector('legend')?.textContent).toBe('Reachable from outside your home');
    const ticks = [...box.querySelectorAll('[data-fw-svc]')];
    expect(ticks.map((b) => /** @type {HTMLElement} */ (b).dataset.fwSvc)).toEqual(Object.keys(NONE));
    expect(ticks.some((b) => /** @type {HTMLInputElement} */ (b).checked)).toBe(false);
    expect(ticks.some((b) => /** @type {HTMLInputElement} */ (b).disabled)).toBe(false);
    expect(box.querySelector('input[type="radio"]')).toBeNull();
    expect(box.querySelector('#fw-home-note')?.textContent).toContain('Your home network is');
    expect(box.querySelector('[data-fw-svc="apps"]')?.parentElement?.textContent).toContain(
      'Apps (the ports they publish)'
    );
  });

  it('where it can: turns on, ticks a service for the outside, and shows a refusal', async () => {
    document.body.innerHTML = '<section id="firewall-card" hidden></section>';
    let st = { enabled: false, outside: { ...NONE }, possible: true, why_not: '', rules: '' };
    vi.spyOn(api, 'get').mockImplementation(async () => st);
    const put = vi.spyOn(api, 'put').mockImplementation(async (_u, body) => {
      st = { ...st, ...body, outside: { ...st.outside, ...body.outside } };
      return st;
    });
    await renderFirewallCard();
    const box = /** @type {HTMLElement} */ (document.getElementById('firewall-card'));
    expect(box.querySelector('#fw-why')).toBeNull();
    expect(box.querySelector('#fw-toggle')?.classList.contains('active')).toBe(false);
    /** @type {HTMLButtonElement} */ (box.querySelector('#fw-toggle')).click();
    await flush();
    expect(put).toHaveBeenLastCalledWith('/api/security/firewall', { enabled: true, outside: NONE });
    expect(box.querySelector('#fw-status')?.textContent).toContain('On: devices at home reach everything');
    // the switch looks on when it is on, as the other cards' switches do
    expect(box.querySelector('#fw-toggle')?.classList.contains('active')).toBe(true);
    const web = /** @type {HTMLInputElement} */ (box.querySelector('[data-fw-svc="web"]'));
    web.checked = true;
    web.dispatchEvent(new Event('change'));
    await flush();
    expect(put.mock.calls.at(-1)?.[1]).toEqual({ enabled: true, outside: { ...NONE, web: true } });
    put.mockRejectedValueOnce(new Error('The firewall rules could not be loaded: bad'));
    /** @type {HTMLButtonElement} */ (box.querySelector('#fw-toggle')).click();
    await flush();
    expect(box.querySelector('#fw-error')?.textContent).toContain('could not be loaded');
  });

  it('shows a refusal in the page’s own words when the server says how it was made', async () => {
    document.body.innerHTML = '<section id="firewall-card" hidden></section>';
    const st = { enabled: false, outside: { ...NONE }, possible: true, why_not: '', rules: '' };
    vi.spyOn(api, 'get').mockResolvedValue(st);
    vi.spyOn(api, 'put').mockRejectedValue(
      new ApiError('server words', { status: 400, body: { detail: 'server words', text: { msg_key: 'fw.title' } } })
    );
    await renderFirewallCard();
    const box = /** @type {HTMLElement} */ (document.getElementById('firewall-card'));
    /** @type {HTMLButtonElement} */ (box.querySelector('#fw-toggle')).click();
    await flush();
    const err = /** @type {HTMLElement} */ (box.querySelector('#fw-error'));
    expect(err.hidden).toBe(false);
    expect(err.textContent).toBe('Firewall');
  });

  it('stays hidden for someone who may not see it', async () => {
    document.body.innerHTML = '<section id="firewall-card"></section>';
    vi.spyOn(api, 'get').mockRejectedValue(new Error('403'));
    expect(await renderFirewallCard()).toBeNull();
    expect(/** @type {HTMLElement} */ (document.getElementById('firewall-card')).hidden).toBe(true);
    expect(await renderFirewallCard(null)).toBeNull();
  });
});
