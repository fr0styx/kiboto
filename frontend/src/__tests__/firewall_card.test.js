/** Audit A13: the firewall card on the Security page. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { renderFirewallCard, whyNot } from '../components/firewall-card.js';

const flush = () => new Promise((r) => setTimeout(r, 10));
const SVC = { web: true, ssh: true, smb: true, nfs: false, webdav: false, sftp: false, tailscale: true, mdns: true };

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

  it('in a container: the reason shown, the switch and choices locked', async () => {
    document.body.innerHTML = '<section id="firewall-card" hidden></section>';
    vi.spyOn(api, 'get').mockResolvedValue({
      enabled: false,
      allow_from: 'lan',
      services: SVC,
      possible: false,
      why_not: 'host',
      rules: 'table inet kiboto',
    });
    await renderFirewallCard();
    const box = /** @type {HTMLElement} */ (document.getElementById('firewall-card'));
    expect(box.hidden).toBe(false);
    expect(box.textContent).toContain('Off: every service on this NAS can be reached.');
    expect(box.querySelector('#fw-why')?.textContent).toContain('Kiboto runs in a container');
    expect(/** @type {HTMLButtonElement} */ (box.querySelector('#fw-toggle')).disabled).toBe(true);
    expect(box.querySelectorAll('fieldset[disabled]').length).toBe(2);
    expect(box.querySelector('pre')?.textContent).toBe('table inet kiboto');
  });

  it('where it can: turns on, changes who and what, and shows a refusal', async () => {
    document.body.innerHTML = '<section id="firewall-card" hidden></section>';
    let st = { enabled: false, allow_from: 'lan', services: { ...SVC }, possible: true, why_not: '', rules: '' };
    vi.spyOn(api, 'get').mockImplementation(async () => st);
    const put = vi.spyOn(api, 'put').mockImplementation(async (_u, body) => {
      st = { ...st, ...body, services: { ...st.services, ...body.services } };
      return st;
    });
    await renderFirewallCard();
    const box = /** @type {HTMLElement} */ (document.getElementById('firewall-card'));
    expect(box.querySelector('#fw-why')).toBeNull();
    expect(/** @type {HTMLInputElement} */ (box.querySelector('[data-fw-svc="web"]')).disabled).toBe(true);
    /** @type {HTMLButtonElement} */ (box.querySelector('#fw-toggle')).click();
    await flush();
    expect(put).toHaveBeenLastCalledWith('/api/security/firewall', { enabled: true, allow_from: 'lan', services: SVC });
    expect(box.textContent).toContain('On: only the services below can be reached.');
    const nfs = /** @type {HTMLInputElement} */ (box.querySelector('[data-fw-svc="nfs"]'));
    nfs.checked = true;
    nfs.dispatchEvent(new Event('change'));
    await flush();
    expect(put.mock.calls.at(-1)?.[1].services.nfs).toBe(true);
    const any = /** @type {HTMLInputElement} */ (box.querySelector('input[value="anywhere"]'));
    any.checked = true;
    any.dispatchEvent(new Event('change'));
    await flush();
    expect(put.mock.calls.at(-1)?.[1].allow_from).toBe('anywhere');
    put.mockRejectedValueOnce(new Error('The firewall rules could not be loaded: bad'));
    /** @type {HTMLButtonElement} */ (box.querySelector('#fw-toggle')).click();
    await flush();
    expect(box.querySelector('#fw-error')?.textContent).toContain('could not be loaded');
  });

  it('stays hidden for someone who may not see it', async () => {
    document.body.innerHTML = '<section id="firewall-card"></section>';
    vi.spyOn(api, 'get').mockRejectedValue(new Error('403'));
    expect(await renderFirewallCard()).toBeNull();
    expect(/** @type {HTMLElement} */ (document.getElementById('firewall-card')).hidden).toBe(true);
    expect(await renderFirewallCard(null)).toBeNull();
  });
});
