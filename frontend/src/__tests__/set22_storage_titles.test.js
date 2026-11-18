/** SET-22 Storage 2: Shared folders and Storage open with their own titles; old links land there. */
import { describe, it, expect, vi, beforeAll } from 'vitest';
import { initManagement } from '../components/management.js';
import { api } from '../api.js';

const shown = (id) => /** @type {HTMLElement} */ (document.getElementById(id)).style.display;
const title = () => document.getElementById('management-header-title-text')?.textContent;

describe('Shared folders and Storage, each with its title (SET-22 Storage 2)', () => {
  beforeAll(() => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    vi.spyOn(api, 'post').mockResolvedValue({});
    Element.prototype.scrollIntoView = vi.fn();
    document.body.innerHTML = `
      <div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"><span id="management-header-title-text"></span></div>
        <div class="mgmt-content-pane">
          <div id="mgmt-sec-storage" class="mgmt-detail-card">
            <div id="mgmt-pane-chassis-twin" class="mgmt-tab-pane"><button id="btn-goto-storage-shares"></button></div>
          </div>
          <div id="mgmt-sec-shares" class="mgmt-detail-card">
            <div id="mgmt-pane-storage-shares" class="mgmt-tab-pane"><div id="mgmt-storage-shares-mount"></div></div>
          </div>
        </div></div></div>`;
    try {
      initManagement();
    } catch (_) {
      /* parts of the window this test doesn't build */
    }
  });

  it('Storage is titled Storage', () => {
    window.openManagementWindow('mgmt-sec-storage', 'mgmt-pane-chassis-twin');
    expect(shown('mgmt-sec-storage')).toBe('block');
    expect(title()).toBe('Storage');
  });

  it('an old link to the shares pane opens Shared folders, its own page', () => {
    window.openManagementWindow('mgmt-sec-storage', 'mgmt-pane-storage-shares');
    expect(shown('mgmt-sec-shares')).toBe('block');
    expect(shown('mgmt-sec-storage')).toBe('none');
    expect(title()).toBe('Shared folders');
  });

  it('the button to the shares opens Shared folders', () => {
    window.openManagementWindow('mgmt-sec-storage', 'mgmt-pane-chassis-twin');
    /** @type {HTMLElement} */ (document.getElementById('btn-goto-storage-shares')).click();
    expect(shown('mgmt-sec-shares')).toBe('block');
    expect(title()).toBe('Shared folders');
  });
});
