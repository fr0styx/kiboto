import { describe, it, expect, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { api } from '../api.js';

const src = (f) => fs.readFileSync(path.resolve(__dirname, '..', f), 'utf8');

describe('the catalog opens in the Apps window (SET-25, Apps finding 14)', () => {
  it('Spotlight and the HTTPS guide no longer press buttons of the hidden Settings page', () => {
    expect(src('components/spotlight.js')).not.toContain('btn-view-docker-catalog');
    expect(src('components/management.js')).not.toContain(
      "openManagementWindow('mgmt-sec-docker', 'mgmt-pane-docker-catalog')"
    );
  });

  it("Spotlight's App Catalog opens the Apps window on its catalog", async () => {
    const { initSpotlight, openSpotlight, filterSpotlightResults } = await import('../components/spotlight.js');
    const open = vi.fn();
    /** @type {any} */ (window).openContainersManager = open;
    document.body.innerHTML = '';
    initSpotlight();
    openSpotlight();
    filterSpotlightResults('App Catalog');
    const item = [...document.querySelectorAll('.spotlight-result-item')].find((e) =>
      e.textContent?.includes('App Catalog')
    );
    expect(item).toBeTruthy();
    /** @type {HTMLElement} */ (item).click();
    await vi.waitFor(() => expect(open).toHaveBeenCalledWith({ view: 'catalog' }));
  });

  it("the HTTPS guide's apps button types its search into the catalog", async () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    const open = vi.fn();
    /** @type {any} */ (window).openContainersManager = open;
    document.body.innerHTML = `<div id="management-modal-overlay"><div id="management-window"><div id="management-window-header"><span id="management-header-title-text"></span></div><div class="mgmt-content-pane"></div></div></div>
      <div id="modal-https-guide-overlay"><button id="modal-https-guide-close"></button><button id="btn-https-guide-apps">Apps</button></div>`;
    const { initManagement } = await import('../components/management.js');
    try {
      initManagement();
    } catch (_) {
      /* parts of the window this test doesn't build */
    }
    /** @type {HTMLElement} */ (document.getElementById('btn-https-guide-apps')).click();
    expect(open).toHaveBeenCalledWith({ view: 'catalog', search: 'reverse proxy' });
  });

  it('the Apps window takes a search for its catalog', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([]);
    const cm = await import('../components/containers-manager.js');
    document.body.innerHTML = '';
    cm.initContainersManager();
    cm.openContainersManager({ view: 'catalog', search: 'plex' });
    expect(/** @type {HTMLInputElement} */ (document.getElementById('cw-catalog-search-input')).value).toBe('plex');
    document.body.innerHTML = '';
    expect(cm.presetCwCatalogSearch('x')).toBe(false);
  });
});
