import { describe, it, expect, vi, beforeEach } from 'vitest';

const get = vi.fn();
const put = vi.fn();
vi.mock('../api.js', () => ({ api: { get, put } }));
const showToast = vi.fn();
const showConfirmToast = vi.fn();
vi.mock('../toast.js', () => ({ showToast, showConfirmToast }));

const hh = await import('../components/household-rules.js');
const ADULTS = hh.ADULT_ROLES;
const ACCESS = {
  roles: [
    { id: 'kid', on: false, search: true },
    { id: 'guest', on: false, search: false },
  ],
};

describe('Household rules (SET-19, Users decision 9)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<section id="hh"><div id="mount"></div></section>';
  });

  it('reads the per-role list as off, adults or some', () => {
    expect(hh.twoStepMode([])).toBe('off');
    expect(hh.twoStepMode(undefined)).toBe('off');
    expect(hh.twoStepMode(ADULTS)).toBe('adults');
    expect(hh.twoStepMode([...ADULTS, 'kid'])).toBe('some');
    expect(hh.twoStepMode(['superadmin'])).toBe('some');
    expect(hh.adultsWithout({ without_two_step: { share_user: 2, kid: 3, superadmin: 1 } })).toBe(3);
    expect(hh.adultsWithout(null)).toBe(0);
  });

  it('shows the two-step choice and the Kib switches; nothing for who may change neither', async () => {
    get.mockImplementation((url) =>
      Promise.resolve(
        url.includes('mfa') ? { required_roles: ['superadmin'], without_two_step: { share_user: 1 } } : ACCESS
      )
    );
    const mount = /** @type {HTMLElement} */ (document.getElementById('mount'));
    await hh.renderHousehold(mount);
    const select = /** @type {HTMLSelectElement} */ (mount.querySelector('[data-hh-two-step]'));
    expect(select.value).toBe('some');
    expect(mount.textContent).toContain('1 adult has not set it up yet.');
    expect(mount.querySelectorAll('[data-kids-ai]').length).toBe(4);
    get.mockRejectedValue(new Error('403'));
    await hh.renderHousehold(mount);
    expect(document.getElementById('hh')?.hidden).toBe(true);
    await hh.renderHousehold(null);
  });

  it('turning it on for adults asks first when some have not set it up; off saves at once', async () => {
    get.mockImplementation((url) =>
      Promise.resolve(url.includes('mfa') ? { required_roles: [], without_two_step: { share_user: 2 } } : null)
    );
    put.mockResolvedValue({});
    const mount = /** @type {HTMLElement} */ (document.getElementById('mount'));
    await hh.renderHousehold(mount);
    let select = /** @type {HTMLSelectElement} */ (mount.querySelector('[data-hh-two-step]'));
    select.value = 'adults';
    select.dispatchEvent(new Event('change'));
    const [, question, onOk] = showConfirmToast.mock.calls[0];
    expect(question).toContain('2 adults have not set it up');
    await onOk();
    expect(put).toHaveBeenCalledWith('/api/security/mfa-policy', { required_roles: ADULTS });
    expect(showToast).toHaveBeenCalledWith('Saved.', 'success');
    select = /** @type {HTMLSelectElement} */ (mount.querySelector('[data-hh-two-step]'));
    select.value = 'off';
    select.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(put).toHaveBeenLastCalledWith('/api/security/mfa-policy', { required_roles: [] }));
    put.mockRejectedValueOnce(
      new Error('Turn on two-step sign-in for yourself first: your own role would require it.')
    );
    get.mockImplementation((url) =>
      Promise.resolve(url.includes('mfa') ? { required_roles: [], without_two_step: {} } : null)
    );
    await hh.renderHousehold(mount);
    select = /** @type {HTMLSelectElement} */ (mount.querySelector('[data-hh-two-step]'));
    select.value = 'adults';
    select.dispatchEvent(new Event('change'));
    await vi.waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        'Turn on two-step sign-in for yourself first: your own role would require it.',
        'error'
      )
    );
  });

  it('saves a Kib switch, and turns it back when saving fails', async () => {
    get.mockImplementation((url) => Promise.resolve(url.includes('mfa') ? null : ACCESS));
    const mount = /** @type {HTMLElement} */ (document.getElementById('mount'));
    await hh.renderHousehold(mount);
    const ask = /** @type {HTMLInputElement} */ (mount.querySelector('[data-kids-ai="roles"][data-role="kid"]'));
    put.mockResolvedValueOnce({});
    ask.checked = true;
    ask.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(ask.disabled).toBe(false));
    expect(put).toHaveBeenCalledWith('/api/ai/access', { roles: { kid: true } });
    put.mockRejectedValueOnce(new Error('no'));
    ask.checked = false;
    ask.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(put).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(ask.disabled).toBe(false));
    expect(ask.checked).toBe(true);
  });
});
