/**
 * Activity -> History -> Sign-ins (SET-27, Activity report section 4, row 5): the security log as
 * sentences, for people who may read it (audit:read). Loaded when the chip is chosen.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { formatTime } from '../format.js';
import { dayLabel } from './events.js';

/** Whether this account may read the security log. */
export function maySeeSignins(user = /** @type {any} */ (globalThis).kibotoUser) {
  const scopes = (user && (user.scopes || user.user?.scopes)) || [];
  return scopes.includes('*') || scopes.includes('audit:read');
}

const WORDS = {
  'auth.login.success': ['signin.ok', '{user} signed in'],
  'auth.login.new_device': ['signin.new_device', '{user} signed in from a new device: {device}'],
  'auth.login.failure': ['signin.failed', 'A sign-in as {user} failed'],
  'auth.login.blocked': ['signin.blocked', '{ip} was blocked after failed sign-ins'],
  'auth.lockout': ['signin.blocked', '{ip} was blocked after failed sign-ins'],
  'smb.login.failure': [
    'signin.smb_failed',
    'File sharing: {count, plural, one {# failed sign-in} other {# failed sign-ins}} as {user}',
  ],
  'auth.login.outside_hours': ['signin.hours', '{user} tried to sign in outside their hours'],
  'auth.logout': ['signin.out', '{user} signed out'],
  'audit.exported': ['signin.exported', '{user} saved the security log as a file'],
  'auth.mfa.enabled': ['signin.mfa_on', '{user} turned on two-step sign-in'],
  'auth.mfa.disabled': ['signin.mfa_off', 'Two-step sign-in was turned off for {user}'],
  'auth.mfa.failure': ['signin.mfa_failed', 'A two-step code for {user} was wrong'],
  'auth.passkey.failure': ['signin.passkey_failed', 'A passkey sign-in failed'],
  'user.created': ['signin.user_created', '{user} added a person'],
  'user.deleted': ['signin.user_deleted', '{user} removed a person'],
  'user.role.changed': ['signin.role', "{user} changed someone's role"],
  'user.password.changed': ['signin.password', 'A password was changed by {user}'],
  'user.status.changed': ['signin.status', '{user} turned an account on or off'],
  'user.signin_hours.changed': ['signin.hours_set', "{user} changed someone's sign-in hours"],
};

/** One entry as a sentence; an unknown kind says what the log calls it. */
export function signinSentence(row) {
  const words = WORDS[row.event_type];
  const params = {
    user: row.actor_username || t('signin.someone', 'Someone'),
    ip: row.actor_ip || '?',
    device: row.details?.device || '?',
    count: Number(row.details?.count) || 1,
  };
  return words ? t(words[0], words[1], params) : `${row.event_type} (${params.user})`;
}

export async function renderSignins(list) {
  let rows;
  try {
    rows = ((await api.get('/api/auth/audit?limit=100')) || {}).audit_logs || [];
  } catch (e) {
    list.textContent = t('signin.unreadable', "The sign-in log couldn't be read: {error}", { error: e?.message || '' });
    return false;
  }
  if (!rows.length) {
    list.textContent = t('signin.none', 'No sign-ins recorded yet.');
    return true;
  }
  list.replaceChildren();
  let day = '';
  for (const r of rows) {
    const label = dayLabel(r.timestamp);
    if (label !== day) {
      day = label;
      const h = document.createElement('h3');
      h.className = 'history-day';
      h.textContent = label;
      list.append(h);
    }
    const item = document.createElement('article');
    item.className = `history-entry is-${r.status === 'success' ? 'ok' : 'warning'}`;
    const text = document.createElement('div');
    text.className = 'history-text';
    const line = document.createElement('div');
    line.className = 'history-message';
    line.textContent = signinSentence(r);
    const when = document.createElement('div');
    when.className = 'history-time';
    when.textContent = [formatTime(new Date(r.timestamp * 1000)), r.actor_ip].filter(Boolean).join(' · ');
    text.append(line, when);
    item.append(text);
    list.append(item);
  }
  return true;
}
