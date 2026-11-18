/** Audit A9: HTTPS at home on Away from home. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { httpsStatus, renderHttpsCard } from '../components/https-card.js';

const flush = () => new Promise((r) => setTimeout(r, 10));
const BASE = {
  enabled: false,
  staging: false,
  hostname: '',
  has_cert: false,
  serving: false,
  last_error: '',
  ddns_ready: true,
  ddns_hostname: 'home.duckdns.org',
  port: 8443,
  days_left: 0,
  terms: 'https://letsencrypt.org/repository/',
};

describe('HTTPS at home (audit A9)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('says off, waiting, ready, serving or why not', () => {
    expect(httpsStatus(null)).toBe('Off');
    expect(httpsStatus(BASE)).toBe('Off');
    expect(httpsStatus({ ...BASE, enabled: true })).toContain('Get a certificate');
    expect(httpsStatus({ ...BASE, enabled: true, last_error: "Let's Encrypt refused: x" })).toBe(
      "No certificate: Let's Encrypt refused: x"
    );
    expect(httpsStatus({ ...BASE, enabled: true, has_cert: true, hostname: 'home.duckdns.org', days_left: 89 })).toBe(
      'Certificate ready for home.duckdns.org (89 days left).'
    );
    expect(
      httpsStatus({
        ...BASE,
        enabled: true,
        has_cert: true,
        serving: true,
        hostname: 'home.duckdns.org',
        days_left: 89,
      })
    ).toContain('https://home.duckdns.org:8443 works');
  });

  it('turns on, gets a certificate, and shows a refusal', async () => {
    document.body.innerHTML = '<div id="https-card" hidden></div>';
    let st = { ...BASE };
    vi.spyOn(api, 'get').mockImplementation(async () => st);
    const put = vi.spyOn(api, 'put').mockImplementation(async (_u, b) => {
      st = { ...st, ...b };
      return st;
    });
    const post = vi.spyOn(api, 'post').mockImplementation(async () => {
      st = { ...st, has_cert: true, serving: true, hostname: 'home.duckdns.org', days_left: 90 };
      return st;
    });
    await renderHttpsCard();
    const box = /** @type {HTMLElement} */ (document.getElementById('https-card'));
    expect(box.hidden).toBe(false);
    expect(box.textContent).toContain('map it in the container settings');
    expect(box.querySelector('#https-get')).toBeNull();
    /** @type {HTMLButtonElement} */ (box.querySelector('#https-toggle')).click();
    await flush();
    expect(put).toHaveBeenLastCalledWith('/api/network/https', { enabled: true, staging: false });
    expect(box.querySelector('a')?.getAttribute('href')).toBe('https://letsencrypt.org/repository/');
    /** @type {HTMLButtonElement} */ (box.querySelector('#https-get')).click();
    await flush();
    expect(post).toHaveBeenCalledWith('/api/network/https/certificate', {});
    expect(box.querySelector('#https-status')?.textContent).toContain('works');
    expect(box.querySelector('#https-get')?.textContent).toBe('Renew now');
    post.mockRejectedValueOnce(new Error('boom'));
    /** @type {HTMLButtonElement} */ (box.querySelector('#https-get')).click();
    await flush();
    expect(box.querySelector('#https-error')?.textContent).toBe('boom');
    put.mockRejectedValueOnce(new Error('nope'));
    /** @type {HTMLButtonElement} */ (box.querySelector('#https-toggle')).click();
    await flush();
    expect(box.querySelector('#https-error')?.textContent).toBe('nope');
  });

  it('needs Dynamic DNS first; hidden when not allowed', async () => {
    document.body.innerHTML = '<div id="https-card" hidden></div>';
    vi.spyOn(api, 'get').mockResolvedValueOnce({ ...BASE, ddns_ready: false });
    await renderHttpsCard();
    const box = /** @type {HTMLElement} */ (document.getElementById('https-card'));
    expect(/** @type {HTMLButtonElement} */ (box.querySelector('#https-toggle')).disabled).toBe(true);
    expect(box.textContent).toContain('Set up Dynamic DNS above first');
    vi.mocked(api.get).mockRejectedValueOnce(new Error('403'));
    expect(await renderHttpsCard(box)).toBeNull();
    expect(box.hidden).toBe(true);
    expect(await renderHttpsCard(null)).toBeNull();
  });
});
