/** Shares R1: share a folder in two steps, which folder (picked, not typed), then who may open it. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { openCreateNetworkShareModal, pickShareFolder } from '../components/chassis-visualizer.js';
import { api } from '../api.js';

const flush = () => new Promise((r) => setTimeout(r, 0));
const el = (id) => document.getElementById(id);

describe('Share a folder in two steps (Shares R1)', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="modal-create-network-share" class="smart-modal-backdrop" style="display:none;">
        <div class="smart-modal-window"><div class="smart-modal-header"><button id="modal-create-share-close-btn"></button></div>
          <form id="create-share-form">
            <input id="create-share-name" value="" /><input id="create-share-path" value="" /><button type="button" id="create-share-pick"></button>
            <input id="create-share-comment" value="" /><input id="create-share-quota-gb" value="" />
            <select id="create-share-security"><option value="private" selected>Private</option></select>
            <input type="checkbox" id="create-share-readonly" /><input type="checkbox" id="create-share-export-smb" checked />
            <input type="checkbox" id="create-share-export-nfs" /><input type="checkbox" id="create-share-timemachine" />
            <div id="create-share-error-box" style="display:none;"></div>
            <button type="button" id="modal-create-share-cancel-btn"></button><button type="submit" id="create-share-submit-btn"></button>
          </form></div></div>`;
  });
  afterEach(() => { vi.restoreAllMocks(); delete window.openFolderBrowser; document.getElementById('who-window')?.remove(); });

  it('Choose… picks the folder and names the share after it', () => {
    window.openFolderBrowser = vi.fn((start, cb) => cb('/mnt/user/Family Photos/'));
    openCreateNetworkShareModal();
    el('create-share-pick').click();
    expect(window.openFolderBrowser).toHaveBeenCalledWith('/mnt/user/', expect.any(Function));
    expect(el('create-share-path').value).toBe('/mnt/user/Family Photos');
    expect(el('create-share-name').value).toBe('family-photos');
    el('create-share-name').value = 'pics';
    window.openFolderBrowser = vi.fn((start, cb) => cb('/mnt/user/Other'));
    expect(pickShareFolder()).toBe(true);
    expect(window.openFolderBrowser).toHaveBeenCalledWith('/mnt/user/Family Photos', expect.any(Function));
    expect(el('create-share-name').value).toBe('pics'); // a name already typed stays
    window.openFolderBrowser = vi.fn((start, cb) => cb(''));
    pickShareFolder();
    expect(el('create-share-path').value).toBe('/mnt/user/Other');
    delete window.openFolderBrowser;
    expect(pickShareFolder()).toBe(false);
  });

  it('after the folder is made, step two asks who may open it', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({ status: 'created' });
    vi.spyOn(api, 'get').mockImplementation(async (url) => (url.endsWith('/who') ? { shares: [{ name: 'pics', people: [{ username: 'ben', name: 'Ben', level: 'none', role: 'share_user' }] }] } : { shares: [] }));
    HTMLDialogElement.prototype.showModal = HTMLDialogElement.prototype.showModal || function () { this.setAttribute('open', ''); };
    openCreateNetworkShareModal();
    el('create-share-name').value = 'pics';
    el('create-share-form').dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(document.getElementById('who-window')).not.toBeNull());
    expect(document.getElementById('who-window-title').textContent).toBe('Who can open "pics"');
    await flush();
  });
});
