/** NUX-20: the Docker settings panel, its cleanup and template-source windows read in the person's language. */
import { describe, it, expect, beforeAll, afterAll, beforeEach, vi } from 'vitest';
import { setLanguage } from '../i18n.js';
import { api } from '../api.js';
import {
  openDockerPruneModal
} from '../components/management.js';

describe('Docker settings in German (NUX-20)', () => {
  beforeAll(async () => { await setLanguage('de'); });
  afterAll(async () => { await setLanguage('en'); });
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="mgmt-pane-docker">
        <table><thead><tr><th class="sortable-th" data-sort-col="name"><span class="docker-sort-indicator"></span></th></tr></thead></table>
        <div id="docker-catalog-grid"></div>
      </div>`;
    vi.restoreAllMocks();
  });

  it('explains every cleanup choice', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    await openDockerPruneModal();
    const modal = document.getElementById('docker-prune-modal-overlay');
    expect(modal.textContent).toContain('Docker aufräumen');
    expect(modal.textContent).toContain('Verwaiste Images entfernen');
    expect(modal.textContent).toContain('Entfernt unbenannte „none“-Build-Schichten');
    expect(modal.textContent).toContain('Freigebbar');
    expect(document.getElementById('dpm-cancel-btn').textContent).toBe('Abbrechen');
    expect(document.getElementById('dpm-confirm-btn').textContent).toContain('Aufräumen und Platz schaffen');
  });

});
