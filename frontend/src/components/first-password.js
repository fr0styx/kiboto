// What comes right after signing in (SET-19): the owner's setup wizard only for someone who can
// configure the NAS while the built-in account has its default password; the own-password dialog
// for a person asked to choose their own; else two-step setup when it is required. A kid signing in
// while the owner still had the default password got the owner's setup wizard.
import { ensureManagementDom } from '../management-dom.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';

/** 'wizard' | 'own_password' | 'mfa' | null, from the sign-in answer. */
export function signInStep(data) {
  const scopes = data?.user?.scopes || [];
  if (data?.is_default_password && (scopes.includes('*') || scopes.includes('system:config'))) return 'wizard';
  if (data?.choose_own_password) return 'own_password';
  if (data?.mfa_setup_required) return 'mfa';
  return null;
}

/** The own-password dialog, with a word on why it opened. */
export async function chooseOwnPassword(user) {
  if (!user?.id) return false;
  await ensureManagementDom();
  const users = await import('./users.js');
  users.showResetPasswordModal(user.id, user.username);
  showToast(t('auth.choose_own_pw', 'Choose your own password to go on.'), 'info');
  return true;
}

/** Runs the step after signing in; wizard and mfa are the callers' own dialogs. */
export function afterSignIn(data, { wizard, mfa }) {
  const step = signInStep(data);
  if (step === 'wizard') wizard();
  else if (step === 'own_password') chooseOwnPassword(data.user);
  else if (step === 'mfa') mfa(data);
  return step;
}
