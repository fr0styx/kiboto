import { describe, it, expect } from 'vitest';
import { toRows, fromRows, readHours, installSigninHours } from '../components/signin-hours.js';
import { hoursText } from '../components/kids-rules.js';

const NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

describe('Sign-in hours as two rows (SET-19 stage 5, decision 5 b)', () => {
  it('stored hours become the two rows, and back', () => {
    expect(toRows(null)).toEqual({ school: { on: true, start: '07:00', end: '20:00' }, weekend: { on: true, start: '09:00', end: '21:00' } });
    expect(toRows({ days: [0, 1, 2, 3, 4], start: '07:30', end: '19:00' }).weekend.on).toBe(false);
    const two = { rows: [{ days: [0, 1, 2, 3, 4], start: '07:00', end: '20:00' }, { days: [5, 6], start: '09:00', end: '22:00' }] };
    expect(toRows(two).weekend).toEqual({ on: true, start: '09:00', end: '22:00' });
    const s = { on: true, start: '07:00', end: '20:00' };
    expect(fromRows(false, s, s)).toEqual({});
    expect(fromRows(true, s, { ...s })).toEqual({ days: [0, 1, 2, 3, 4, 5, 6], start: '07:00', end: '20:00' });
    expect(fromRows(true, s, { on: false, start: '', end: '' })).toEqual({ days: [0, 1, 2, 3, 4], start: '07:00', end: '20:00' });
    expect(fromRows(true, s, { on: true, start: '09:00', end: '22:00' })).toEqual(two);
  });

  it('the form shows two rows; unticking one hides its times and says no sign-in', () => {
    const box = document.createElement('div');
    document.body.replaceChildren(box);
    const changed = installSigninHours(box, { signin_hours: { rows: [{ days: [0, 1, 2, 3, 4], start: '07:00', end: '20:00' }, { days: [5, 6], start: '09:00', end: '22:00' }] } });
    expect(box.querySelectorAll('.kb-hours-row').length).toBe(2);
    const weekend = /** @type {HTMLInputElement} */ (box.querySelector('[data-hours-row="weekend"]'));
    weekend.checked = false;
    weekend.dispatchEvent(new Event('change', { bubbles: true }));
    expect(/** @type {HTMLElement} */ (box.querySelector('[data-hours-closed="weekend"]')).hidden).toBe(false);
    expect(changed()).toBe(true);
    expect(readHours(box)).toEqual({ days: [0, 1, 2, 3, 4], start: '07:00', end: '20:00' });
  });

  it('the kids card says both rows', () => {
    expect(hoursText({ rows: [{ days: [0, 1, 2, 3, 4], start: '07:00', end: '20:00' }, { days: [5, 6], start: '09:00', end: '22:00' }] }, NAMES)).toBe('Mon–Fri 07:00–20:00 · Sat, Sun 09:00–22:00');
  });
});
