import { describe, it, expect, vi, beforeEach } from 'vitest';

const showResetPasswordModal = vi.fn();
vi.mock('../components/users.js', () => ({ showResetPasswordModal }));
vi.mock('../management-dom.js', () => ({ ensureManagementDom: vi.fn(() => Promise.resolve()) }));
const showToast = vi.fn();
vi.mock('../toast.js', () => ({ showToast }));

const { signInStep, afterSignIn, chooseOwnPassword } = await import('../components/first-password.js');
const owner = { id: 'u1', username: 'mum', scopes: ['*'] };
const kid = { id: 'u2', username: 'zoe', scopes: ['files:read'] };

describe('what comes after signing in (SET-19)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('the setup wizard only for someone who can configure the NAS', () => {
    expect(signInStep({ is_default_password: true, user: owner })).toBe('wizard');
    expect(signInStep({ is_default_password: true, user: { scopes: ['system:config'] } })).toBe('wizard');
    expect(signInStep({ is_default_password: true, user: kid })).toBeNull(); // a kid got the owner's wizard
    expect(signInStep({ is_default_password: true, choose_own_password: true, user: kid })).toBe('own_password');
    expect(signInStep({ mfa_setup_required: true, user: kid })).toBe('mfa');
    expect(signInStep({})).toBeNull();
    expect(signInStep(null)).toBeNull();
  });

  it('runs the step: wizard, own password or two-step setup', async () => {
    const wizard = vi.fn();
    const mfa = vi.fn();
    expect(afterSignIn({ is_default_password: true, user: owner }, { wizard, mfa })).toBe('wizard');
    expect(wizard).toHaveBeenCalledTimes(1);
    const data = { mfa_setup_required: true, user: kid };
    afterSignIn(data, { wizard, mfa });
    expect(mfa).toHaveBeenCalledWith(data);
    afterSignIn({ choose_own_password: true, user: kid }, { wizard, mfa });
    await vi.waitFor(() => expect(showResetPasswordModal).toHaveBeenCalledWith('u2', 'zoe'));
    expect(showToast).toHaveBeenCalledWith('Choose your own password to go on.', 'info');
    expect(afterSignIn({}, { wizard, mfa })).toBeNull();
  });

  it('no account, no dialog', async () => {
    expect(await chooseOwnPassword(null)).toBe(false);
    expect(showResetPasswordModal).not.toHaveBeenCalled();
  });
});
