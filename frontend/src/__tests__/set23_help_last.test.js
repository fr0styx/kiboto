import { describe, it, expect, vi } from 'vitest';
import { api } from '../api.js';
import { installHealthSignal } from '../components/management/health-signal.js';

describe('Help improve Kiboto sits last on General (SET-23)', () => {
  it('goes after the report for support, not between Software update and This server', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ available: true, enabled: false, preview: {} });
    document.body.innerHTML = `<div class="mgmt-detail-body"><div class="drawer-card"><div id="update-status-box"></div></div>
      <div class="drawer-card" id="server"></div><div class="drawer-card" id="support"></div></div>`;
    await installHealthSignal(document);
    const card = /** @type {HTMLElement} */ (document.getElementById('health-signal-card'));
    expect(card.previousElementSibling?.id).toBe('support');
    expect(card.parentElement?.lastElementChild).toBe(card);
    vi.restoreAllMocks();
  });
});
