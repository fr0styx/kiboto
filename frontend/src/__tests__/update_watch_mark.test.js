import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { refreshUpdateMark } from '../components/update-mark.js';

afterEach(() => vi.restoreAllMocks());

describe('the daily update check in Settings (Settings decision 5)', () => {
  it('marks General when an update is ready and keeps the switch in step', async () => {
    document.body.innerHTML = '<span id="mgmt-sidebar-update-badge" hidden></span><input type="checkbox" id="update-daily-toggle">';
    vi.spyOn(api, 'get').mockResolvedValue({ daily: true, available: true, latest: '2.0.4' });
    const put = vi.spyOn(api, 'put').mockResolvedValue({ daily: false });
    await refreshUpdateMark();
    const mark = /** @type {HTMLElement} */ (document.getElementById('mgmt-sidebar-update-badge'));
    const box = /** @type {HTMLInputElement} */ (document.getElementById('update-daily-toggle'));
    expect(mark.hidden).toBe(false);
    expect(mark.title).toBe('Version 2.0.4 is ready');
    expect(box.checked).toBe(true);
    box.checked = false;
    box.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(put).toHaveBeenCalledWith('/api/system/update-watch', { daily: false }));
    put.mockRejectedValueOnce(new Error('no right'));
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(box.checked).toBe(false));
  });

  it('no mark without an update, and nothing when it cannot be read', async () => {
    document.body.innerHTML = '<span id="mgmt-sidebar-update-badge"></span>';
    vi.spyOn(api, 'get').mockResolvedValueOnce({ daily: true, available: false, latest: '' });
    await refreshUpdateMark();
    expect(/** @type {HTMLElement} */ (document.getElementById('mgmt-sidebar-update-badge')).hidden).toBe(true);
    vi.spyOn(api, 'get').mockRejectedValueOnce(new Error('403'));
    expect(await refreshUpdateMark()).toBeNull();
  });
});
