import { describe, it, expect } from 'vitest';
import { dayNames, installSigninHours, readHours } from '../components/signin-hours.js';

describe('sign-in hours fields (COMP-13)', () => {
  it('names the days Monday first', () => {
    expect(dayNames('en-GB')).toEqual(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']);
  });

  it('shows the hours a person has and reads them back', () => {
    const box = document.body.appendChild(document.createElement('div'));
    const changed = installSigninHours(box, { signin_hours: { days: [5, 6], start: '09:00', end: '21:00' } });
    expect(box.querySelector('[data-hours-on]').checked).toBe(true);
    expect(readHours(box)).toEqual({ days: [5, 6], start: '09:00', end: '21:00' });
    expect(changed()).toBe(false);
    box.querySelector('[data-hours-row="school"]').click(); // school days on, with their own times (SET-19)
    expect(changed()).toBe(true);
    expect(readHours(box)).toEqual({ rows: [{ days: [0, 1, 2, 3, 4], start: '07:00', end: '20:00' }, { days: [5, 6], start: '09:00', end: '21:00' }] });
  });

  it('without hours the fields start hidden with both rows, and off means no limit', () => {
    const box = document.body.appendChild(document.createElement('div'));
    installSigninHours(box, {});
    expect(box.querySelector('[data-hours-fields]').hidden).toBe(true);
    expect(readHours(box)).toEqual({});
    const on = box.querySelector('[data-hours-on]');
    on.checked = true;
    on.dispatchEvent(new Event('change', { bubbles: true }));
    expect(box.querySelector('[data-hours-fields]').hidden).toBe(false);
    expect(readHours(box)).toEqual({ rows: [{ days: [0, 1, 2, 3, 4], start: '07:00', end: '20:00' }, { days: [5, 6], start: '09:00', end: '21:00' }] });
  });

  it('is hidden for accounts that manage people', () => {
    const box = document.body.appendChild(document.createElement('div'));
    installSigninHours(box, {}, { canBeLimited: false });
    expect(box.hidden).toBe(true);
  });
});
