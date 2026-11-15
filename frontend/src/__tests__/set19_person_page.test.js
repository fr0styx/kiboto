import { describe, it, expect, vi, beforeEach } from 'vitest';

const get = vi.fn();
const post = vi.fn();
const apiFetch = vi.fn();
vi.mock('../api.js', () => ({ api: { get, post }, apiFetch }));
const showToast = vi.fn();
vi.mock('../toast.js', () => ({ showToast, showConfirmToast: vi.fn(), showBottomSheet: vi.fn() }));
vi.mock('../utils.js', async (orig) => ({ ...(await orig()), copyText: vi.fn(() => Promise.resolve()) }));

const pp = await import('../components/person-page.js');
const lea = { id: 'u2', username: 'lea', display_name: 'Lea', email: 'lea@home', role_id: 'kid', status: 'active', mfa_enabled: false, storage_quota_bytes: 5 * 1024 ** 3 };
const deps = () => ({ me: { id: 'u1' }, roleName: (r) => ({ kid: 'Kid', share_user: 'Family member' })[r] || r, roleOptionsHtml: '<option value="share_user">Family member</option>', reload: vi.fn(), resetPassword: vi.fn(), setStatus: vi.fn(() => Promise.resolve()), remove: vi.fn() });

describe("a person's page (SET-19)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="users-pane-list"><button id="row">Lea</button></div>';
    get.mockImplementation((url) => Promise.resolve(url.includes('sessions') ? { sessions: [{ id: 'abc', user_agent: 'Firefox', ip_address: '10.0.0.5', last_active_at: 1 }] } : { enabled: true }));
  });

  it('opens in place of the list, with every section, and Back returns', async () => {
    document.getElementById('row')?.focus();
    const d = deps();
    const page = /** @type {HTMLElement} */ (await pp.openPersonPage(lea, d));
    expect(document.getElementById('users-pane-list')?.hidden).toBe(true);
    expect(document.activeElement?.id).toBe('pp-title');
    expect(page.querySelector('.pp-sub')?.textContent).toBe('Signs in as lea · Kid');
    expect(/** @type {HTMLSelectElement} */ (page.querySelector('[data-pp-role]')).value).toBe('kid'); // added, never blank
    expect(page.querySelector('[data-pp-hours-wrap]')?.hasAttribute('hidden')).toBe(false);
    await vi.waitFor(() => expect(page.querySelector('[data-pp-devices]')?.textContent).toContain('Firefox'));
    await vi.waitFor(() => expect(page.querySelector('[data-pp-away]')?.hasAttribute('hidden')).toBe(false));
    /** @type {HTMLElement} */ (page.querySelector('[data-pp-reset]')).click();
    expect(d.resetPassword).toHaveBeenCalledWith('u2', 'lea');
    /** @type {HTMLElement} */ (page.querySelector('[data-pp-remove]')).click();
    expect(d.remove).toHaveBeenCalledWith('u2', 'lea');
    /** @type {HTMLElement} */ (page.querySelector('[data-pp-back]')).click();
    expect(page.hidden).toBe(true);
    expect(document.getElementById('users-pane-list')?.hidden).toBe(false);
    expect(document.activeElement?.id).toBe('row');
  });

  it('Save sends the form, the role only when changed', async () => {
    const d = deps();
    const page = /** @type {HTMLElement} */ (await pp.openPersonPage(lea, d));
    const form = /** @type {HTMLFormElement} */ (page.querySelector('[data-pp-form]'));
    expect(pp.saveBody(form, lea, null)).toEqual({ display_name: 'Lea', email: 'lea@home', storage_quota_bytes: 5 * 1024 ** 3 });
    /** @type {HTMLSelectElement} */ (page.querySelector('[data-pp-role]')).value = 'share_user';
    /** @type {HTMLInputElement} */ (page.querySelector('[data-pp-quota]')).value = '';
    expect(pp.saveBody(form, lea, { days: [0], start: '07:00', end: '20:00' })).toEqual({
      display_name: 'Lea', email: 'lea@home', role_id: 'share_user', storage_quota_bytes: 0, signin_hours: { days: [0], start: '07:00', end: '20:00' },
    });
    apiFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(d.reload).toHaveBeenCalled());
    apiFetch.mockResolvedValueOnce({ ok: false, status: 400, json: async () => ({ detail: 'bad email' }) });
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Error: bad email', 'error'));
  });

  it('turning off goes back to the list; no ending yourself; no hours for who manages people', async () => {
    const d = deps();
    let page = /** @type {HTMLElement} */ (await pp.openPersonPage(lea, d));
    /** @type {HTMLElement} */ (page.querySelector('[data-pp-status]')).click();
    await vi.waitFor(() => expect(d.setStatus).toHaveBeenCalledWith('u2', 'disabled'));
    await vi.waitFor(() => expect(page.hidden).toBe(true));
    page = /** @type {HTMLElement} */ (await pp.openPersonPage({ ...lea, id: 'u1', role_id: 'superadmin', status: 'disabled' }, d));
    expect(page.querySelector('[data-pp-status], [data-pp-remove]')).toBeNull();
    expect(page.querySelector('[data-pp-hours-wrap]')?.hasAttribute('hidden')).toBe(true);
    expect(/** @type {HTMLSelectElement} */ (page.querySelector('[data-pp-role]')).disabled).toBe(true);
  });

  it('copies an app sign-in link; says when devices cannot be read', async () => {
    post.mockResolvedValueOnce({ url: 'https://id/lc/tok' });
    const page = /** @type {HTMLElement} */ (await pp.openPersonPage(lea, deps()));
    await vi.waitFor(() => expect(page.querySelector('[data-pp-away]')?.hasAttribute('hidden')).toBe(false));
    /** @type {HTMLElement} */ (page.querySelector('[data-pp-link]')).click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Sign-in link copied. It works once, for 24 hours.', 'success'));
    post.mockRejectedValueOnce(new Error('Pocket ID is down'));
    /** @type {HTMLElement} */ (page.querySelector('[data-pp-link]')).click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Pocket ID is down', 'error'));
    get.mockRejectedValue(new Error('403'));
    const again = /** @type {HTMLElement} */ (await pp.openPersonPage(lea, deps()));
    await vi.waitFor(() => expect(again.querySelector('[data-pp-devices]')?.textContent).toBe("Couldn't read where they are signed in."));
    expect(again.querySelector('[data-pp-away]')?.hasAttribute('hidden')).toBe(true);
  });

  it('devices and nothing to open', async () => {
    expect(pp.devicesHtml([])).toContain('Not signed in anywhere.');
    expect(pp.devicesHtml([{ id: 'x' }])).toContain('Unknown browser');
    document.body.innerHTML = '';
    expect(await pp.openPersonPage(lea, deps())).toBeNull();
    pp.closePersonPage();
  });
});
