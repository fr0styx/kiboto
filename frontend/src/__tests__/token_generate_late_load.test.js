import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// settings.js loads after the first paint, often after DOMContentLoaded has fired. Its token form
// was wired in a DOMContentLoaded listener, which then never ran: Generate did nothing (#68).
describe('The API token form when settings.js loads late', () => {
  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = `
      <div id="management-modal-overlay"></div>
      <input id="new-token-name" value="Home Assistant">
      <select id="new-token-kind"><option value="monitoring" selected>Monitoring</option></select>
      <button id="btn-generate-token">Generate</button>
      <div id="api-tokens-list"></div>
      <div id="api-token-created" hidden></div>`;
  });
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('wires Generate even though the page finished loading before the module', async () => {
    expect(document.readyState).not.toBe('loading');
    const apiModule = await import('../api.js');
    const post = vi.spyOn(apiModule.api, 'post').mockResolvedValue({ token: 'kb_test_value' });
    vi.spyOn(apiModule.api, 'get').mockResolvedValue([]);
    await import('../components/settings.js');
    document.getElementById('btn-generate-token').click();
    await new Promise((r) => setTimeout(r, 0));
    expect(post).toHaveBeenCalledWith('/api/tokens', { name: 'Home Assistant', preset: 'monitoring' });
  });
});
