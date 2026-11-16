/** Audit A8: the Dynamic DNS card on Away from home. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { ddnsStatus, renderDdnsCard } from '../components/ddns-card.js';

const flush = () => new Promise((r) => setTimeout(r, 10));
const OFF = { enabled: false, provider: 'duckdns', hostname: '', token_set: false, last_ok: 0, last_error: '', last_ip: '' };

describe('Dynamic DNS card (audit A8)', () => {
  afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = ''; });

  it('says off, waiting, working or why it failed', () => {
    expect(ddnsStatus(null)).toBe('Off');
    expect(ddnsStatus(OFF)).toBe('Off');
    expect(ddnsStatus({ ...OFF, enabled: true, hostname: 'home.duckdns.org' })).toBe('On: home.duckdns.org is updated within 5 minutes');
    expect(ddnsStatus({ ...OFF, enabled: true, hostname: 'home.duckdns.org', last_ok: 1700000000, last_ip: '203.0.113.7' })).toContain('home.duckdns.org points to 203.0.113.7');
    expect(ddnsStatus({ ...OFF, enabled: true, hostname: 'h', last_ok: 1700000000 })).toContain('points to ?');
    expect(ddnsStatus({ ...OFF, enabled: true, last_error: 'DuckDNS refused the update.' })).toBe('Not updated: DuckDNS refused the update.');
  });

  it('saves the settings, sends the token once, turns on and updates now', async () => {
    document.body.innerHTML = '<div id="ddns-card"></div>';
    let st = { ...OFF };
    vi.spyOn(api, 'get').mockImplementation(async () => st);
    const put = vi.spyOn(api, 'put').mockImplementation(async (_u, body) => { st = { ...st, ...body, token_set: true, hostname: 'home.duckdns.org' }; return st; });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ ...OFF, hostname: 'home.duckdns.org', last_ok: 1700000000, last_ip: '203.0.113.7' });
    await renderDdnsCard();
    const box = /** @type {HTMLElement} */ (document.getElementById('ddns-card'));
    expect(box.textContent).toContain('A name alone opens nothing');
    expect(/** @type {HTMLButtonElement} */ (box.querySelector('#ddns-now')).disabled).toBe(true);
    /** @type {HTMLInputElement} */ (box.querySelector('#ddns-hostname')).value = 'home';
    /** @type {HTMLInputElement} */ (box.querySelector('#ddns-token')).value = 'tok';
    box.querySelector('#ddns-form')?.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(put).toHaveBeenLastCalledWith('/api/network/ddns', { enabled: false, provider: 'duckdns', hostname: 'home', token: 'tok' });
    expect(/** @type {HTMLInputElement} */ (box.querySelector('#ddns-token')).placeholder).toContain('Saved');
    /** @type {HTMLButtonElement} */ (box.querySelector('#ddns-toggle')).click();
    await flush();
    expect(put).toHaveBeenLastCalledWith('/api/network/ddns', { enabled: true, provider: 'duckdns', hostname: 'home.duckdns.org', token: null });
    expect(box.querySelector('#ddns-toggle')?.getAttribute('aria-pressed')).toBe('true');
    /** @type {HTMLButtonElement} */ (box.querySelector('#ddns-now')).click();
    await flush();
    expect(post).toHaveBeenCalledWith('/api/network/ddns/update', {});
    expect(box.querySelector('#ddns-status')?.textContent).toContain('points to 203.0.113.7');
  });

  it('shows refusals, a failed update, switches the provider help, and a load failure', async () => {
    document.body.innerHTML = '<div id="ddns-card"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({ ...OFF, provider: 'cloudflare', hostname: 'nas.example.com', token_set: true });
    vi.spyOn(api, 'put').mockRejectedValue(new Error('That name can\'t be used.'));
    const post = vi.spyOn(api, 'post').mockResolvedValue({ ...OFF, last_error: 'Cloudflare refused the token.' });
    await renderDdnsCard();
    const box = /** @type {HTMLElement} */ (document.getElementById('ddns-card'));
    expect(box.textContent).toContain('Zone: Read and DNS: Edit');
    /** @type {HTMLButtonElement} */ (box.querySelector('#ddns-toggle')).click();
    await flush();
    expect(box.querySelector('#ddns-error')?.textContent).toBe("That name can't be used.");
    /** @type {HTMLButtonElement} */ (box.querySelector('#ddns-now')).click();
    await flush();
    expect(box.querySelector('#ddns-error')?.textContent).toBe('Cloudflare refused the token.');
    post.mockRejectedValueOnce(new Error('offline'));
    /** @type {HTMLButtonElement} */ (box.querySelector('#ddns-now')).click();
    await flush();
    expect(box.querySelector('#ddns-error')?.textContent).toBe('offline');
    const sel = /** @type {HTMLSelectElement} */ (box.querySelector('#ddns-provider'));
    sel.value = 'duckdns';
    sel.dispatchEvent(new Event('change'));
    expect(box.querySelector('#ddns-token-help')?.textContent).toContain('duckdns.org');
    expect(/** @type {HTMLInputElement} */ (box.querySelector('#ddns-hostname')).placeholder).toBe('home.duckdns.org');
    sel.value = 'cloudflare';
    sel.dispatchEvent(new Event('change'));
    expect(/** @type {HTMLInputElement} */ (box.querySelector('#ddns-hostname')).placeholder).toBe('nas.example.com');
    vi.mocked(api.get).mockRejectedValueOnce(new Error('403'));
    expect(await renderDdnsCard(box)).toBeNull();
    expect(box.textContent).toContain('could not be loaded: 403');
    expect(await renderDdnsCard(null)).toBeNull();
  });
});
