import { describe, it, expect } from 'vitest';
import { personStatus, personMarks, personRowHtml, inviteRowHtml, peopleRowsHtml, peopleMessageHtml } from '../components/people-rows.js';

const lea = { id: 'u2', username: 'lea', display_name: 'Lea', role_id: 'kid', status: 'active', signed_in: 2, mfa_enabled: true, storage_quota_bytes: 5 * 2 ** 30 };

describe('People as rows (SET-19)', () => {
  it('one status line', () => {
    expect(personStatus(lea)).toBe('Signed in on 2 devices');
    expect(personStatus({ ...lea, signed_in: 1 })).toBe('Signed in on 1 device');
    expect(personStatus({ ...lea, signed_in: 0 })).toBe('Not signed in now');
    expect(personStatus({ ...lea, signed_in: undefined })).toBe('Not signed in now');
    expect(personStatus({ ...lea, status: 'disabled' })).toBe('Turned off');
  });

  it('marks for two-step sign-in and a storage limit', () => {
    expect(personMarks(lea, '5 GB')).toEqual(['Two-step', 'Limit 5 GB']);
    expect(personMarks({ ...lea, mfa_enabled: false, storage_quota_bytes: 0 }, '')).toEqual([]);
  });

  it('a row opens the person; no turning off or deleting yourself', () => {
    const opts = { me: { id: 'u1' }, roleName: 'Kid', quotaText: '5 GB' };
    document.body.innerHTML = `<ul>${personRowHtml(lea, opts)}${personRowHtml({ ...lea, id: 'u1', username: 'mum', display_name: '', mfa_enabled: false, storage_quota_bytes: 0 }, opts)}</ul>`;
    const [row, mine] = document.querySelectorAll('.person-row');
    expect(row.querySelector('.person-open')?.textContent).toContain('@lea · Kid');
    expect(row.querySelector('.btn-delete-user')).not.toBeNull();
    expect(mine.textContent).toContain('You');
    expect(mine.querySelector('.person-name')?.textContent).toContain('mum');
    expect(mine.querySelector('.btn-delete-user, .btn-toggle-user')).toBeNull();
    expect(mine.querySelector('.person-marks')).toBeNull();
  });

  it('invited people are rows too, only while the invite works', () => {
    const inv = { id: 'i1', role_id: 'kid', note: 'Grandma', expires_at: 2000000000, active: true };
    expect(inviteRowHtml(inv, 'Kid')).toContain('Grandma');
    expect(inviteRowHtml({ ...inv, note: '' }, 'Kid')).toContain('<span class="person-name">Kid</span>');
    const html = peopleRowsHtml([lea], [inv, { ...inv, id: 'i2', active: false }], { me: null, roleName: () => 'Kid', quotaText: () => '5 GB' });
    document.body.innerHTML = `<ul>${html}</ul>`;
    expect(document.querySelectorAll('.person-row').length).toBe(2);
    expect(document.querySelector('[data-invite-cancel="i1"]')).not.toBeNull();
    expect(peopleRowsHtml([], null, { me: null, roleName: () => '', quotaText: () => '' })).toBe('');
  });

  it('a message in the list', () => {
    expect(peopleMessageHtml('Loading <people>')).toBe('<li class="people-msg">Loading &lt;people&gt;</li>');
    expect(peopleMessageHtml('x', true)).toContain('is-crit');
  });
});
