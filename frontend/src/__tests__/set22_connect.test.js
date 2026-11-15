import { describe, it, expect, vi, beforeEach } from 'vitest';

const get = vi.fn();
vi.mock('../api.js', () => ({ api: { get } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
const copyText = vi.fn();
vi.mock('../utils.js', async (orig) => ({ ...(await orig()), copyText }));
const askForSmbPassword = vi.fn();
vi.mock('../components/smb-password.js', () => ({ askForSmbPassword }));
const sc = await import('../components/share-connect.js');

describe('how to connect (SET-22, Shares 3)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
    HTMLDialogElement.prototype.showModal = vi.fn();
    HTMLDialogElement.prototype.close = vi.fn();
  });

  it('the Windows and Mac addresses of a folder', () => {
    expect(sc.addresses('Family Photos', '192.168.1.20')).toEqual({ windows: '\\\\192.168.1.20\\Family Photos', mac: 'smb://192.168.1.20/Family%20Photos' });
  });

  it('which password: the Kiboto one, a separate one with two-step sign-in, or the host one', () => {
    const a = sc.addresses('photos', '10.0.0.2');
    expect(sc.connectHtml('photos', a)).toContain('Sign in with your Kiboto name and password.');
    const two = sc.connectHtml('photos', a, { twoStep: true });
    expect(two).toContain('separate password for shared folders');
    expect(two).toContain('data-sc-make');
    expect(sc.connectHtml('photos', a, { host: 'Unraid' })).toContain('Use the name and password you use for Unraid.');
  });

  it('the window copies an address and makes the separate password', async () => {
    get.mockImplementation(async (url) => (url.includes('mfa') ? { mfa_enabled: true } : { address: '10.0.0.2' }));
    copyText.mockResolvedValue(undefined);
    const dlg = await sc.openConnect('photos');
    /** @type {HTMLElement} */ (dlg.querySelector('[data-sc-copy="mac"]')).click();
    await vi.waitFor(() => expect(copyText).toHaveBeenCalledWith('smb://10.0.0.2/photos'));
    /** @type {HTMLElement} */ (dlg.querySelector('[data-sc-make]')).click();
    await vi.waitFor(() => expect(askForSmbPassword).toHaveBeenCalled());
    /** @type {HTMLElement} */ (dlg.querySelector('[data-sc-close]')).click();
    expect(document.getElementById('share-connect')).toBeNull();
  });

  it('a button on each card, once', () => {
    document.body.innerHTML = '<div id="g"><div data-share="photos"><div class="share-card-actions"></div></div><div data-share="media"></div></div>';
    const grid = /** @type {HTMLElement} */ (document.getElementById('g'));
    expect(sc.addConnectButtons(grid)).toBe(1);
    expect(sc.addConnectButtons(grid)).toBe(0);
    expect(grid.querySelector('[data-sc-open]')?.textContent).toBe('How to connect');
  });
});
