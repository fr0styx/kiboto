import { describe, it, expect, afterEach } from 'vitest';
import { statusText } from '../components/app-condition.js';
import { setLanguage } from '../i18n.js';

afterEach(async () => {
  await setLanguage('en');
});

describe("Docker's status line in the person's language", () => {
  it('says when an app started and how long ago one stopped', () => {
    expect(statusText('Up 9 minutes')).toBe('Started 9 minutes ago');
    expect(statusText('Up About an hour')).toBe('Started 1 hour ago');
    expect(statusText('Up Less than a second')).toBe('Started 1 second ago');
    expect(statusText('Up 2 days (healthy)')).toBe('Started 2 days ago · health check OK');
    expect(statusText('Up 3 hours (Paused)')).toBe('Started 3 hours ago');
    expect(statusText('Up 5 seconds (health: starting)')).toBe('Started 5 seconds ago');
    expect(statusText('Exited (1) 2 hours ago')).toBe('2 hours ago');
    expect(statusText('Exited (0) About a minute ago')).toBe('1 minute ago');
    expect(statusText('Created')).toBe('');
    expect(statusText('')).toBe('');
  });

  it('shows what it does not know as Docker wrote it', () => {
    expect(statusText('Removal In Progress')).toBe('Removal In Progress');
    expect(statusText('Restarting (1) 5 seconds ago')).toBe('Restarting (1) 5 seconds ago');
    expect(statusText('Up forever')).toBe('Up forever');
  });

  it('is grammatical in German', async () => {
    await setLanguage('de');
    expect(statusText('Up 2 days')).toBe('Gestartet vor 2 Tagen');
    expect(statusText('Exited (1) 2 hours ago')).toBe('vor 2 Stunden');
  });
});
