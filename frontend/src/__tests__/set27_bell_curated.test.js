/** SET-27 rest: the bell is the curated view: only what needs a look, and a way to all of it. */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { state } from '../state.js';
import { renderNotificationCenter } from '../components/dock/notifications.js';

describe('the bell (SET-27 rest)', () => {
  it('with nothing to look at, it says so and where everything else is', () => {
    document.body.innerHTML = '<div id="notif-center-list"></div>';
    state.latestStats = { events: [{ id: 'a', ts: 1, level: 'info', title: 'Zip made' }] };
    renderNotificationCenter();
    expect(document.getElementById('notif-center-list')?.textContent).toContain(
      'Nothing needs a look. Everything that happened is in Activity.'
    );
  });

  it('lists a problem, and has no filter code left without buttons', () => {
    document.body.innerHTML = '<div id="notif-center-list"></div>';
    state.latestStats = { events: [{ id: 'b', ts: 2, level: 'error', title: 'Backup failed' }] };
    renderNotificationCenter();
    expect(document.getElementById('notif-center-list')?.textContent).toContain('Backup failed');
    const src = readFileSync(resolve(__dirname, '../components/dock/notifications.js'), 'utf8');
    expect(src).not.toContain('notif-filter-btn');
  });

  it('the footer opens all activity under its current name', () => {
    const html = readFileSync(resolve(__dirname, '../../index.html'), 'utf8');
    expect(html).toContain('data-i18n="notif.see_all_activity">See all activity</button>');
    expect(html).not.toContain('Everything that happened: the Event Log');
  });
});
