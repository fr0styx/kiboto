/** AI decision 8: Settings → Kib is titled "Kib", as in the sidebar (it said "AI"). */
import { describe, it, expect, vi, beforeAll } from 'vitest';
import { initManagement } from '../components/management.js';
import { api } from '../api.js';

describe('Settings → Kib title', () => {
  beforeAll(() => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    vi.spyOn(api, 'post').mockResolvedValue({});
    Element.prototype.scrollIntoView = vi.fn();
    document.body.innerHTML = `
      <div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"><span id="management-header-title-text"></span></div>
        <div class="mgmt-content-pane">
          <div id="mgmt-sec-ai" class="mgmt-detail-card">
            <button class="mgmt-inner-tab active" id="mgmt-tab-ai-index" data-tab-target="mgmt-pane-ai-index"></button>
            <div id="mgmt-pane-ai-index" class="mgmt-tab-pane"><div id="kib-status-mount"></div></div>
          </div>
        </div></div></div>`;
    try { initManagement(); } catch (_) { /* parts of the window this test doesn't build */ }
  });

  it('is titled Kib', () => {
    window.openManagementWindow('mgmt-sec-ai');
    expect(document.getElementById('management-header-title-text').textContent).toBe('Kib');
  });
});
