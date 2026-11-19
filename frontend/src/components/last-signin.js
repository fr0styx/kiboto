// After signing in: "Last sign-in: yesterday 21:14, Safari on iPhone." (re-audit, 19 Nov 2026).
// Someone who did not sign in then sees at once that somebody else did.
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { formatDateTime } from '../format.js';
import { deviceName } from '../device-name.js';

/** The sentence, or '' when this is the account's first sign-in. */
export function lastSignInText(prev) {
  if (!prev || !prev.at) return '';
  const when = formatDateTime(prev.at * 1000);
  const device = deviceName(prev.user_agent);
  return device
    ? t('login.last_signin', 'Last sign-in: {when}, {device}.', { when, device })
    : t('login.last_signin_plain', 'Last sign-in: {when}.', { when });
}

export function sayLastSignIn(prev) {
  const text = lastSignInText(prev);
  if (!text) return false;
  showToast(text, 'info');
  return true;
}
