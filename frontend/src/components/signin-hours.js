/**
 * Sign-in hours in the edit-person dialog (COMP-13): which days and times a family account may
 * be signed in. The server enforces them; this only edits them.
 */
import { t } from '../i18n.js';
import { currentLocale, formatTime } from '../format.js';
import { state } from '../state.js';

/** Monday first, as the server counts (0 = Monday). */
export function dayNames(locale = currentLocale()) {
  const fmt = new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' });
  return [5, 6, 7, 8, 9, 10, 11].map((d) => fmt.format(new Date(Date.UTC(2024, 1, d)))); // 5 Feb 2024 was a Monday
}

export const SCHOOL_DAYS = [0, 1, 2, 3, 4];
export const WEEKEND = [5, 6];

/** Stored hours -> the two rows the form shows (Users decision 5 b): school days and weekends. A
 * row is on when the stored hours cover any of its days; older one-range hours fill both rows. */
export function toRows(hours) {
  const rows = hours ? (Array.isArray(hours.rows) ? hours.rows : [hours]) : [];
  const pick = (days, start, end) => {
    const r = rows.find((x) => (x.days || []).some((d) => days.includes(d)));
    return r ? { on: true, start: r.start, end: r.end } : { on: !hours, start, end };
  };
  return { school: pick(SCHOOL_DAYS, '07:00', '20:00'), weekend: pick(WEEKEND, '09:00', '21:00') };
}

/** The two rows -> what PUT /api/users/{id} takes: one range when both match, {} for no limit. */
export function fromRows(on, school, weekend) {
  if (!on) return {};
  const rows = [];
  if (school.on) rows.push({ days: SCHOOL_DAYS, start: school.start, end: school.end });
  if (weekend.on) rows.push({ days: WEEKEND, start: weekend.start, end: weekend.end });
  if (rows.length === 2 && rows[0].start === rows[1].start && rows[0].end === rows[1].end) return { days: [...SCHOOL_DAYS, ...WEEKEND], start: school.start, end: school.end };
  if (rows.length === 1) return rows[0];
  return { rows };
}

/** The fields' state -> what PUT /api/users/{id} takes ({} removes the limit). */
export function readHours(box) {
  const row = (name) => ({
    on: Boolean(box.querySelector(`[data-hours-row="${name}"]`)?.checked),
    start: box.querySelector(`[data-hours-start="${name}"]`)?.value || '',
    end: box.querySelector(`[data-hours-end="${name}"]`)?.value || '',
  });
  return fromRows(Boolean(box.querySelector('[data-hours-on]')?.checked), row('school'), row('weekend'));
}

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (v === true) n.setAttribute(k, '');
    else if (v !== false && v !== null && v !== undefined) n.setAttribute(k, v);
  }
  children.flat().forEach((c) => c !== null && c !== undefined && n.append(c));
  return n;
}

/** Builds the fields into `box` for this person; returns a function that says whether they changed. */
export function installSigninHours(box, user, { canBeLimited = true } = {}) {
  if (!box) return () => false;
  box.hidden = !canBeLimited;
  const hours = user?.signin_hours || null;
  const on = el('input', { type: 'checkbox', 'data-hours-on': true });
  on.checked = Boolean(hours);
  const rows = toRows(hours);
  const names = dayNames();
  const rowEl = (key, label, r) => {
    const tick = el('input', { type: 'checkbox', 'data-hours-row': key });
    tick.checked = r.on;
    const start = el('input', { type: 'time', class: 'tz-select-input', 'data-hours-start': key, 'aria-label': `${label}: ${t('hours.from', 'From')}` });
    start.value = r.start;
    const end = el('input', { type: 'time', class: 'tz-select-input', 'data-hours-end': key, 'aria-label': `${label}: ${t('hours.until', 'Until')}` });
    end.value = r.end;
    const times = el('div', { class: 'kb-hours-times' }, el('label', {}, t('hours.from', 'From'), ' ', start), el('label', {}, t('hours.until', 'Until'), ' ', end));
    times.hidden = !r.on;
    tick.addEventListener('change', () => { times.hidden = !tick.checked; });
    return el('div', { class: 'kb-hours-row', role: 'group', 'aria-label': label },
      el('label', { class: 'kb-hours-row-name' }, tick, el('span', { text: label })),
      times,
      el('span', { class: 'kb-sub', 'data-hours-closed': key, text: t('hours.closed', 'No sign-in these days'), hidden: r.on }));
  };
  const school = t('hours.school', 'School days ({first}–{last})', { first: names[0], last: names[4] });
  const weekend = t('hours.weekend', 'Weekends ({first}–{last})', { first: names[5], last: names[6] });
  const fields = el('div', { class: 'kb-hours', 'data-hours-fields': true },
    rowEl('school', school, rows.school),
    rowEl('weekend', weekend, rows.weekend),
    el('div', { class: 'kb-sub', text: serverTimeHint() }));
  fields.addEventListener('change', (e) => {
    const key = /** @type {HTMLElement} */ (e.target).getAttribute('data-hours-row');
    const note = key && fields.querySelector(`[data-hours-closed="${key}"]`);
    if (note) /** @type {HTMLElement} */ (note).hidden = /** @type {HTMLInputElement} */ (e.target).checked;
  });
  fields.hidden = !hours;
  box.replaceChildren(el('label', { class: 'kb-toggle' }, on, el('span', { text: t('hours.only_at', 'Only at these times') })), fields);
  let changed = false;
  on.addEventListener('change', () => { fields.hidden = !on.checked; });
  box.addEventListener('change', () => { changed = true; });
  return () => changed;
}

/** The hint names the server's zone and its time now, so "server time" means something (NUX-10). */
export function serverTimeHint(zone = state.currentTimezone, now = Date.now()) {
  if (!zone) return t('hours.hint', "Server time. Outside these hours this person can't sign in, and an open session stops until they start again.");
  let time;
  try {
    time = formatTime(now, { hour: '2-digit', minute: '2-digit', timeZone: zone });
  } catch {
    time = ''; // an unknown zone: no time shown
  }
  return t('hours.hint_zone', "Server time ({zone}, now {time}). Outside these hours this person can't sign in, and an open session stops until they start again.", { zone, time });
}
