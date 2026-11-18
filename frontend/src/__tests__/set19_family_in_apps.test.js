import { describe, it, expect, vi, beforeEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const get = vi.fn();
vi.mock('../api.js', () => ({ api: { get } }));
const renderFamilyFilter = vi.fn();
vi.mock('../components/family-filter.js', () => ({ renderFamilyFilter }));
const renderFamilyCalendar = vi.fn();
vi.mock('../components/family-calendar.js', () => ({ renderFamilyCalendar }));
const renderFamilySignin = vi.fn();
vi.mock('../components/family-signin.js', () => ({ renderFamilySignin }));

const af = await import('../components/apps-family.js');
const html = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');

describe('the family set-ups live in Apps (SET-19 stage 5, decision 10)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('People keeps link rows, not the cards', () => {
    expect(html).toContain('id="people-family-links"');
    for (const id of ['family-filter-mount', 'family-calendar-mount', 'family-signin-mount'])
      expect(html).not.toContain(`id="${id}"`);
  });

  it('the Apps group fills its cards when it opens, and opens from a link row', async () => {
    document.body.innerHTML = af.appsFamilyHtml();
    af.installAppsFamily(document);
    expect(af.installAppsFamily(document)).toBe(false); // bound once
    Element.prototype.scrollIntoView = vi.fn();
    expect(af.openFamily(document, 'calendar')).toBe(true);
    const group = /** @type {HTMLDetailsElement} */ (document.getElementById('apps-family'));
    expect(group.open).toBe(true);
    group.dispatchEvent(new Event('toggle'));
    await vi.waitFor(() => expect(renderFamilyCalendar).toHaveBeenCalled());
    expect(renderFamilyFilter).toHaveBeenCalled();
    expect(renderFamilySignin).toHaveBeenCalled();
    expect(document.getElementById('fc-title')?.scrollIntoView).toHaveBeenCalled();
  });

  it('each row says its state, and a failed read says so', async () => {
    get.mockImplementation(async (url) => {
      if (url === '/api/family-filter')
        return { user: 'admin', has_password: true, people: { mia: { devices: ['10.0.0.5'] }, leo: { devices: [] } } };
      if (url.includes('office-suite')) return { installed: true, running: false };
      throw new Error('403');
    });
    const st = await af.familyStates();
    expect(st).toEqual({ filter: 'on', filtered: 1, calendar: 'stopped', signin: 'unknown' });
    expect(af.stateText('filter', st)).toBe('1 person filtered');
    expect(af.stateText('calendar', st)).toBe('The office suite is stopped');
    expect(af.stateText('signin', st)).toBe("Couldn't read its state");
    expect(af.stateText('signin', { signin: 'off' })).toBe('Not set up');
  });

  it('a link row opens the card in Apps', async () => {
    get.mockResolvedValue(null);
    const open = vi.fn();
    /** @type {any} */ (window).openContainersManager = open;
    document.body.innerHTML = '<div id="m"></div>';
    const mount = /** @type {HTMLElement} */ (document.getElementById('m'));
    await af.renderFamilyLinks(mount);
    expect(mount.querySelectorAll('.pf-row').length).toBe(3);
    /** @type {HTMLElement} */ (mount.querySelector('[data-open-family="signin"]')).click();
    expect(open).toHaveBeenCalledWith({ view: 'family', part: 'signin' });
    expect(await af.renderFamilyLinks(null)).toBeNull();
  });
});
