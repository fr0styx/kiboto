import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../utils.js', async (orig) => ({ ...(await orig()), copyTextToClipboard: vi.fn() }));
const { copyTextToClipboard } = await import('../utils.js');
const { renderEventLog, dayLabel, filterEvents } = await import('../components/events.js');
const { ROUTES } = await import('../router.js');

const now = Math.floor(Date.now() / 1000);
const EVENTS = [
  { id: 3, ts: now - 60, level: 'error', title: 'Backup failed', message: 'The copy to the USB disk stopped.', link: 'backup' },
  { id: 2, ts: now - 120, level: 'info', title: 'Backup finished', message: 'Photos were copied.' },
  { id: 1, ts: now - 86400 - 3600, level: 'warning', title: 'Drive is warm', message: 'sda reached 52 °C.' },
];

beforeEach(() => {
  document.body.innerHTML = '<div><div id="events-list"></div></div>';
});

describe('Activity -> History reads by day (SET-27 Activity 2b)', () => {
  it('names the days', () => {
    const today = new Date(2026, 10, 16, 12);
    expect(dayLabel(new Date(2026, 10, 16, 1).getTime() / 1000, today)).toBe('Today');
    expect(dayLabel(new Date(2026, 10, 15, 23).getTime() / 1000, today)).toBe('Yesterday');
    expect(dayLabel(new Date(2026, 10, 10, 9).getTime() / 1000, today)).not.toMatch(/Today|Yesterday/);
  });

  it('filters by Needs a look and by words', () => {
    expect(filterEvents(EVENTS, 'look').map((e) => e.id)).toEqual([3, 1]);
    expect(filterEvents(EVENTS, 'all', 'photos').map((e) => e.id)).toEqual([2]);
    expect(filterEvents(EVENTS, 'all', '').length).toBe(3);
  });

  it('draws day headings, Open for an entry with a page, details folded with Copy', () => {
    renderEventLog(EVENTS);
    const list = /** @type {HTMLElement} */ (document.getElementById('events-list'));
    expect([...list.querySelectorAll('.history-day')].map((h) => h.textContent)).toEqual(['Today', 'Yesterday']);
    const first = /** @type {HTMLElement} */ (list.querySelector('.history-entry'));
    expect(first.textContent).toContain('Backup failed');
    const open = vi.spyOn(ROUTES, 'backup').mockImplementation(() => {});
    /** @type {HTMLElement} */ (first.querySelector('.history-open')).click();
    expect(open).toHaveBeenCalled();
    const details = /** @type {HTMLElement} */ (first.querySelector('.history-details'));
    expect(details.hidden).toBe(true);
    /** @type {HTMLElement} */ (first.querySelector('.history-more')).click();
    expect(details.hidden).toBe(false);
    /** @type {HTMLElement} */ (first.querySelector('.history-copy')).click();
    expect(copyTextToClipboard).toHaveBeenCalled();
    expect(list.querySelectorAll('.history-entry')[1].querySelector('.history-open')).toBeNull(); // no page of its own
  });

  it('the chips and the search filter the drawn list; nothing found says so', () => {
    renderEventLog(EVENTS);
    const bar = /** @type {HTMLElement} */ (document.querySelector('.history-controls'));
    /** @type {HTMLElement} */ (bar.querySelector('[data-filter="look"]')).click();
    expect(document.querySelectorAll('.history-entry').length).toBe(2);
    const search = /** @type {HTMLInputElement} */ (bar.querySelector('.history-search'));
    search.value = 'nothing like this';
    search.dispatchEvent(new Event('input'));
    expect(document.getElementById('events-list')?.textContent).toContain('Nothing in the history matches.');
    search.value = '';
    search.dispatchEvent(new Event('input'));
    /** @type {HTMLElement} */ (bar.querySelector('[data-filter="all"]')).click();
    expect(document.querySelectorAll('.history-entry').length).toBe(3);
  });

  it('an empty history says nothing has happened yet', () => {
    renderEventLog([]);
    expect(document.getElementById('events-list')?.textContent).toContain('Nothing has happened yet');
  });
});
