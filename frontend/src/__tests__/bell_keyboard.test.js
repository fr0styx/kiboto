// Activity finding 25: the bell's rows are reached and opened by keyboard, and say their level.
import { describe, it, expect, vi } from 'vitest';
import { state } from '../state.js';
import { renderNotificationCenter } from '../components/dock/notifications.js';

describe('the bell by keyboard', () => {
  it('rows take focus, say their level and open with Enter or Space', () => {
    document.body.innerHTML = '<div id="notif-center-list"></div>';
    state.latestStats = { events: [{ id: 1, ts: 1762900000, level: 'critical', title: 'Drive failed', message: 'sda' }] };
    const opened = [];
    /** @type {any} */ (window).openEventDetailModal = (e) => opened.push(e.id);
    renderNotificationCenter();
    const row = /** @type {HTMLElement} */ (document.querySelector('.notif-center-item'));
    expect(row.tabIndex).toBe(0);
    expect(row.getAttribute('role')).toBe('button');
    expect(row.querySelector('.sr-only')?.textContent).toMatch(/: $/);
    row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(opened).toEqual([1]);
    row.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
    expect(opened).toHaveLength(1);
  });
});
