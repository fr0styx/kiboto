import { describe, it, expect, vi, beforeEach } from 'vitest';

const get = vi.fn();
const post = vi.fn();
const apiFetch = vi.fn();
vi.mock('../api.js', () => ({ api: { get, post }, apiFetch }));
const showToast = vi.fn();
vi.mock('../toast.js', () => ({ showToast }));
const grantShares = vi.fn(() => Promise.resolve(true));
vi.mock('../components/share-access.js', () => ({
  grantShares,
  shareChoicesHtml: (shares) =>
    shares
      .map(
        (s) =>
          `<select data-add-user-share="${s.name}"><option value="none">No access</option><option value="read">Can view</option><option value="write">Can view and change</option></select>`
      )
      .join(''),
}));
vi.mock('../utils.js', async (orig) => ({ ...(await orig()), copyText: vi.fn(() => Promise.resolve()) }));

const ap = await import('../components/add-person.js');
const flush = () => new Promise((r) => setTimeout(r, 0));
const form = () => /** @type {HTMLFormElement} */ (document.querySelector('.ap-dialog'));
const submit = async () => {
  form().dispatchEvent(new Event('submit', { cancelable: true }));
  await flush();
  await flush();
};
const set = (sel, value) => {
  /** @type {HTMLInputElement} */ (form().querySelector(sel)).value = value;
};

describe('Add a person in three steps (SET-19)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<button id="opener">Add</button>';
    get.mockResolvedValue({ shares: [{ name: 'family' }, { name: 'media' }] });
  });

  it('suggests a sign-in name and keeps a role, folders and limits for the next person', () => {
    expect(ap.suggestUsername('Zoé Martín')).toBe('zoemartin');
    expect(ap.suggestUsername('7 X')).toBe('');
    expect(ap.suggestUsername('')).toBe('');
    const like = ap.newState({
      role: 'kid',
      shares: { family: 'read' },
      hours: { days: [0] },
      quotaGb: 5,
      how: 'invite',
      name: 'Mia',
    });
    expect(like).toMatchObject({
      step: 1,
      name: '',
      role: 'kid',
      shares: { family: 'read' },
      quotaGb: 5,
      how: 'invite',
    });
    expect(ap.canInvite('superadmin')).toBe(false);
    expect(ap.canLimit('kid')).toBe(true);
    expect(ap.inviteMessage('Mia', 'https://x/#/invite/t')).toContain('https://x/#/invite/t');
  });

  it('creates a kid now: name, role, folders, hours, then the account with what was chosen', async () => {
    document.getElementById('opener')?.focus();
    const onDone = vi.fn();
    await ap.openAddPerson({ onDone });
    expect(form().getAttribute('role')).toBe('dialog');
    expect(form().textContent).toContain('Step 1 of 3: Who');
    await submit(); // no name yet
    expect(showToast).toHaveBeenCalledWith('Write their name first.', 'error');
    set('[data-ap-name]', 'Mia Ölz');
    /** @type {HTMLInputElement} */ (form().querySelector('input[value="kid"]')).checked = true;
    await submit();
    expect(form().textContent).toContain('Step 2 of 3: What they can use');
    expect(form().querySelector('[data-ap-hours-wrap]')?.hasAttribute('hidden')).toBe(false);
    set('select[data-add-user-share="family"]', 'write');
    set('[data-ap-quota]', '20');
    await submit();
    expect(form().textContent).toContain('Step 3 of 3: How they get in');
    expect(/** @type {HTMLInputElement} */ (form().querySelector('[data-ap-username]')).value).toBe('miaolz');
    await submit(); // no password
    expect(showToast).toHaveBeenLastCalledWith(
      'Choose a sign-in name and a password of 8 characters or more.',
      'error'
    );
    set('[data-ap-password]', 'First-Pass-123');
    apiFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ user: { id: 'u9' } }) });
    await submit();
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());
    const body = JSON.parse(apiFetch.mock.calls[0][1].body);
    expect(body).toEqual({
      username: 'miaolz',
      display_name: 'Mia Ölz',
      password: 'First-Pass-123',
      role_id: 'kid',
      storage_quota_bytes: 20 * 1024 ** 3,
      must_change_password: true,
    });
    expect(grantShares).toHaveBeenCalledWith('miaolz', { family: 'write' });
    expect(form().textContent).toContain('Mia Ölz was added.');
    /** @type {HTMLElement} */ (form().querySelector('[data-ap-again]')).click();
    expect(form().textContent).toContain('Step 1 of 3');
    expect(/** @type {HTMLInputElement} */ (form().querySelector('input[value="kid"]')).checked).toBe(true);
    /** @type {HTMLElement} */ (form().querySelector('[data-ap-close]')).click();
    expect(document.querySelector('.ap-backdrop')).toBeNull();
    expect(document.activeElement?.id).toBe('opener');
  });

  it('or sends an invite link with the folders and hours, and copies the link or a message', async () => {
    post.mockResolvedValueOnce({ link: '/#/invite/tok123' });
    await ap.openAddPerson({});
    set('[data-ap-name]', 'Grandma');
    /** @type {HTMLInputElement} */ (form().querySelector('input[value="guest"]')).checked = true;
    await submit();
    set('select[data-add-user-share="media"]', 'read');
    await submit();
    const invite = /** @type {HTMLInputElement} */ (form().querySelector('input[value="invite"]'));
    invite.checked = true;
    invite.dispatchEvent(new Event('change'));
    expect(form().querySelector('[data-ap-create]')?.hasAttribute('hidden')).toBe(true);
    set('[data-ap-days]', '3');
    await submit();
    await vi.waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0]).toEqual([
      '/api/invites',
      {
        role_id: 'guest',
        note: 'Grandma',
        days: 3,
        quota_gb: 0,
        max_uses: 1,
        shares: { media: 'read' },
        signin_hours: null,
      },
    ]);
    expect(form().querySelector('.ap-link')?.textContent).toContain('#/invite/tok123');
    /** @type {HTMLElement} */ (form().querySelector('[data-ap-copy="message"]')).click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Copied.', 'info'));
  });

  it('no invite for an administrator; a refusal is shown; Back keeps the answers', async () => {
    await ap.openAddPerson({});
    set('[data-ap-name]', 'Sam');
    /** @type {HTMLInputElement} */ (form().querySelector('input[value="superadmin"]')).checked = true;
    await submit();
    expect(form().querySelector('[data-ap-hours-wrap]')?.hasAttribute('hidden')).toBe(true);
    await submit();
    expect(/** @type {HTMLInputElement} */ (form().querySelector('input[value="invite"]')).disabled).toBe(true);
    /** @type {HTMLElement} */ (form().querySelector('[data-ap-back]')).click();
    /** @type {HTMLElement} */ (form().querySelector('[data-ap-back]')).click();
    expect(/** @type {HTMLInputElement} */ (form().querySelector('[data-ap-name]')).value).toBe('Sam');
    await submit();
    await submit();
    set('[data-ap-password]', 'First-Pass-123');
    apiFetch.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({ detail: "User 'sam' already exists." }),
    });
    await submit();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("User 'sam' already exists.", 'error'));
  });

  it('works without the folders list (no right to manage them)', async () => {
    get.mockRejectedValue(new Error('403'));
    await ap.openAddPerson({});
    set('[data-ap-name]', 'Ola');
    await submit();
    expect(form().querySelector('.ap-shares')).toBeNull();
  });
});
