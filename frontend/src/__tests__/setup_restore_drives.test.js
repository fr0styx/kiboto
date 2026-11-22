// A fresh install on a machine of its own offers, in setup, to look on its drives for the earlier settings.
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
  auth: { setToken: vi.fn(), getToken: vi.fn() },
  ApiError: class extends Error {},
}));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('../components/dock.js', () => ({ bringToFront: vi.fn() }));
vi.mock('../management-dom.js', () => ({ onManagementDom: (fn) => fn() }));
vi.mock('../components/share-access.js', () => ({ grantShares: vi.fn(async () => {}) }));
const card = vi.hoisted(() => ({ lookWhenShown: vi.fn() }));
vi.mock('../components/pool-copy-card.js', () => card);

const byId = (id) => /** @type {any} */ (document.getElementById(id));
const DOM = `
  <div id="setup-wizard-modal" class="open">
    <div class="smart-modal-body">
      <div data-setup-step="1"><h3>Welcome</h3>
        <button id="setup-restore-box"></button><button id="setup-restore-drives" hidden></button>
        <div id="setup-restore-note" hidden></div></div>
      <div data-setup-step="2"><h3>Password</h3>
        <input id="setup-current-pwd"><input id="setup-new-pwd"><input id="setup-confirm-pwd"></div>
      <div data-setup-step="3"><h3>Alerts</h3><input id="setup-notif-url"></div>
      <div class="footer"><button id="setup-wizard-skip"></button><button id="setup-wizard-submit"></button></div>
    </div>
  </div>
  <div id="setup-wizard-err" style="display:none"></div>`;

let W, api;
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('setup on a machine of its own', () => {
  beforeEach(async () => {
    document.body.innerHTML = DOM;
    vi.resetModules();
    ({ api } = await import('../api.js'));
    W = await import('../components/setup-wizard.js');
    vi.clearAllMocks();
    api.post.mockResolvedValue({});
    api.put.mockResolvedValue({});
  });

  it('offers the drives only on a machine set up for Kiboto', async () => {
    const b = document.createElement('button');
    b.hidden = true;
    api.get.mockResolvedValueOnce({ managed: true });
    await W.offerDrives(b);
    expect(b.hidden).toBe(false);
    api.get.mockResolvedValueOnce({ managed: false });
    await W.offerDrives(b);
    expect(b.hidden).toBe(true);
    api.get.mockRejectedValueOnce(new Error('403'));
    b.hidden = false;
    await W.offerDrives(b);
    expect(b.hidden).toBe(true);
  });

  it('after the password is saved, Backup opens and looks on the drives', async () => {
    api.get.mockImplementation(async (url) => (url === '/api/system/machine' ? { managed: true } : {}));
    W.initSetupWizard();
    await flush();
    expect(byId('setup-restore-drives').hidden).toBe(false);
    byId('setup-restore-drives').click();
    expect(byId('setup-restore-note').hidden).toBe(false);
    byId('setup-current-pwd').value = 'ABCD-EFGH-JKLM';
    byId('setup-new-pwd').value = 'Chosen-Pass-1';
    byId('setup-confirm-pwd').value = 'Chosen-Pass-1';
    const opened = vi.fn();
    /** @type {any} */ (window).openManagementSection = opened;
    byId('setup-wizard-submit').click();
    await vi.waitFor(() => expect(opened).toHaveBeenCalledWith('mgmt-pane-backups'));
    expect(card.lookWhenShown).toHaveBeenCalledTimes(1);
    delete (/** @type {any} */ (window).openManagementSection);
  });
});
