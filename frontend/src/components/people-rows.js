// People as rows (SET-19, Users report section 5): one row per person with one status line and
// marks for two-step sign-in and a storage limit; invited people are rows too. The row opens the
// person's page (person-page.js), which has every action. On a phone the rows
// wrap instead of scrolling sideways.
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { formatDateTime } from '../format.js';

/** One line on where the person stands. */
export function personStatus(u) {
  if (u.status !== 'active') return t('users.status_disabled', 'Turned off');
  const n = Number(u.signed_in || 0);
  if (n > 0)
    return t('people.signed_in_n', '{n, plural, one {Signed in on # device} other {Signed in on # devices}}', { n });
  return t('people.not_signed_in', 'Not signed in now');
}

/** The marks after the name: two-step sign-in, a storage limit. */
export function personMarks(u, quotaText) {
  const marks = [];
  if (u.mfa_enabled) marks.push(t('people.mark_two_step', 'Two-step'));
  if (u.storage_quota_bytes > 0) marks.push(t('people.mark_limit', 'Limit {size}', { size: quotaText }));
  return marks;
}

export function personRowHtml(u, { me, roleName, quotaText }) {
  const isSelf = me && me.id === u.id;
  const active = u.status === 'active';
  const name = u.display_name || u.username;
  const marks = personMarks(u, quotaText)
    .map((m) => `<span class="person-mark">${escapeHtml(m)}</span>`)
    .join('');
  return `<li class="person-row${active ? '' : ' is-off'}" data-id="${escapeHtml(u.id)}">
    <button type="button" class="person-open btn-edit-user" data-id="${escapeHtml(u.id)}">
      <span class="person-avatar" aria-hidden="true">${escapeHtml((name[0] || 'U').toUpperCase())}</span>
      <span class="person-main">
        <span class="person-name">${escapeHtml(name)}${isSelf ? ` <span class="person-you">${escapeHtml(t('users.you', 'You'))}</span>` : ''}</span>
        <span class="person-sub">@${escapeHtml(u.username)} · ${escapeHtml(roleName)}</span>
        <span class="person-status">${escapeHtml(personStatus(u))}</span>
      </span>
      ${marks ? `<span class="person-marks">${marks}</span>` : ''}
    </button>
  </li>`;
}

/** An invite still waiting: a row with Cancel invite. */
export function inviteRowHtml(inv, roleName) {
  return `<li class="person-row is-invited" data-invite="${escapeHtml(inv.id)}">
    <span class="person-avatar" aria-hidden="true">✉</span>
    <span class="person-main">
      <span class="person-name">${escapeHtml(inv.note || roleName)}</span>
      <span class="person-sub">${escapeHtml(roleName)}</span>
      <span class="person-status">${escapeHtml(t('people.invited_until', 'Invited, link works until {date}', { date: formatDateTime(Number(inv.expires_at) * 1000) }))}</span>
    </span>
    <span class="person-actions">
      <button type="button" class="btn-pill-toggle is-small" data-invite-cancel="${escapeHtml(inv.id)}">${escapeHtml(t('people.cancel_invite', 'Cancel invite'))}</button>
    </span>
  </li>`;
}

/** The people, then the invites still waiting. */
export function peopleRowsHtml(users, invites, opts) {
  return [
    ...users.map((u) =>
      personRowHtml(u, { me: opts.me, roleName: opts.roleName(u.role_id), quotaText: opts.quotaText(u) })
    ),
    ...(invites || []).filter((i) => i.active).map((i) => inviteRowHtml(i, opts.roleName(i.role_id))),
  ].join('');
}

/** A message in the list's place (loading, a failure, nobody yet). */
export function peopleMessageHtml(text, crit = false) {
  return `<li class="people-msg${crit ? ' is-crit' : ''}">${escapeHtml(text)}</li>`;
}
