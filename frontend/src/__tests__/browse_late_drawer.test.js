/** #71: the card-copy drawer is loaded after the page, and its Browse button still opens the picker. */
import { describe, it, expect, vi } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn() }));
vi.mock('../components/dock.js', () => ({
  DockManager: { register: vi.fn(), unregister: vi.fn(), minimize: vi.fn() },
  bringToFront: vi.fn(),
}));

document.body.innerHTML = `
  <div id="folder-browser-modal"><div class="smart-modal-window">
    <button id="fb-min"></button><button id="fb-close"></button>
    <div id="fb-current-path"></div>
    <input id="fb-search-bar"><button id="fb-sort-btn">A-Z</button>
    <input id="fb-new-folder-name"><button id="fb-create-folder">+ Create</button>
    <div id="fb-list"></div>
    <button id="fb-cancel"></button><button id="fb-select"></button>
  </div></div>`;

const { api } = await import('../api.js');
await import('../folder-browser.js');
window.dispatchEvent(new Event('DOMContentLoaded'));

describe('the Browse button of a drawer loaded later', () => {
  it('opens the picker at the folder in the field, and the pick lands there', async () => {
    const drawer = document.createElement('div');
    drawer.innerHTML = `<input id="btn-copy-dst" value="/mnt/storage/photos/"><button id="btn-browse-dst"><span>Browse</span></button>`;
    document.body.appendChild(drawer); // after the page loaded, as drawer-dom.js does
    const dirs = [{ name: 'Holiday', path: '/mnt/storage/photos/Holiday/' }];
    const request = vi.spyOn(api, 'request').mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ current: '/mnt/storage/photos/', roots: ['/mnt/storage'], dirs }),
    });
    /** @type {HTMLElement} */ (drawer.querySelector('#btn-browse-dst span')).click();
    await vi.waitFor(() => expect(request).toHaveBeenCalled());
    expect(String(request.mock.calls[0][1] || request.mock.calls[0][0])).toContain('photos');
    expect(document.getElementById('folder-browser-modal').classList.contains('open')).toBe(true);
    await vi.waitFor(() => expect(document.getElementById('fb-list').textContent).toContain('Holiday'));
    document.getElementById('fb-select').click();
    await vi.waitFor(() =>
      expect(/** @type {HTMLInputElement} */ (document.getElementById('btn-copy-dst')).value).toContain(
        '/mnt/storage/photos'
      )
    );
  });
});
