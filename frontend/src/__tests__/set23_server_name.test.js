import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { showServerName } from '../components/management/system.js';

describe("This server shows the server's name (SET-23)", () => {
  afterEach(() => vi.restoreAllMocks());

  it('uses the name the household gave it, and keeps Kiboto without one', async () => {
    document.body.innerHTML = '<div id="about-server-name">Kiboto</div>';
    const el = /** @type {HTMLElement} */ (document.getElementById('about-server-name'));
    vi.spyOn(api, 'get').mockResolvedValueOnce({ server_name: '  Living room NAS ' });
    expect(await showServerName(el)).toBe('Living room NAS');
    expect(el.textContent).toBe('Living room NAS');
    el.textContent = 'Kiboto';
    vi.spyOn(api, 'get').mockResolvedValueOnce({ server_name: '' });
    expect(await showServerName(el)).toBeNull();
    expect(el.textContent).toBe('Kiboto');
    vi.spyOn(api, 'get').mockRejectedValueOnce(new Error('403'));
    expect(await showServerName(el)).toBeNull();
    expect(await showServerName(null)).toBeNull();
  });
});
