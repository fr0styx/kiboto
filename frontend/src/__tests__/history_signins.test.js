import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { api } from '../api.js';
import { maySeeSignins, signinSentence, renderSignins } from '../components/history-signins.js';
import { renderEventLog } from '../components/events.js';

afterEach(() => vi.restoreAllMocks());
beforeEach(() => {
  /** @type {any} */ (globalThis).kibotoUser = null;
});

const now = Math.floor(Date.now() / 1000);

describe('History -> Sign-ins (Activity report section 4, row 5)', () => {
  it('only for people who may read the security log', () => {
    expect(maySeeSignins({ scopes: ['*'] })).toBe(true);
    expect(maySeeSignins({ user: { scopes: ['audit:read'] } })).toBe(true);
    expect(maySeeSignins({ scopes: ['files:read'] })).toBe(false);
    expect(maySeeSignins(null)).toBe(false);
  });

  it('writes each entry as a sentence', () => {
    expect(signinSentence({ event_type: 'auth.login.success', actor_username: 'anna' })).toBe('anna signed in');
    expect(signinSentence({ event_type: 'auth.lockout', actor_ip: '192.168.1.9' })).toBe('192.168.1.9 was blocked after failed sign-ins');
    expect(signinSentence({ event_type: 'auth.login.failure' })).toBe('A sign-in as Someone failed');
    expect(signinSentence({ event_type: 'odd.thing', actor_username: 'ben' })).toBe('odd.thing (ben)');
  });

  it('draws the log by day, says when there is none, and when it cannot be read', async () => {
    const list = document.createElement('div');
    vi.spyOn(api, 'get').mockResolvedValueOnce({ audit_logs: [{ event_type: 'auth.login.success', actor_username: 'anna', actor_ip: '10.0.0.2', status: 'success', timestamp: now - 60 }] });
    expect(await renderSignins(list)).toBe(true);
    expect(list.querySelector('.history-day')?.textContent).toBe('Today');
    expect(list.textContent).toContain('anna signed in');
    vi.spyOn(api, 'get').mockResolvedValueOnce({ audit_logs: [] });
    await renderSignins(list);
    expect(list.textContent).toBe('No sign-ins recorded yet.');
    vi.spyOn(api, 'get').mockRejectedValueOnce(new Error('403'));
    expect(await renderSignins(list)).toBe(false);
    expect(list.textContent).toContain("couldn't be read");
  });

  it('the chip shows for an administrator and switches History to the sign-in log', async () => {
    /** @type {any} */ (globalThis).kibotoUser = { scopes: ['*'] };
    document.body.innerHTML = '<div><div id="events-list"></div></div>';
    renderEventLog([{ id: 1, ts: now, level: 'info', title: 'x', message: 'y' }]);
    const chip = /** @type {HTMLElement} */ (document.querySelector('[data-filter="signins"]'));
    await vi.waitFor(() => expect(chip.hidden).toBe(false));
    vi.spyOn(api, 'get').mockResolvedValue({ audit_logs: [{ event_type: 'auth.logout', actor_username: 'anna', status: 'success', timestamp: now }] });
    chip.click();
    await vi.waitFor(() => expect(document.getElementById('events-list')?.textContent).toContain('anna signed out'));
    renderEventLog([{ id: 2, ts: now, level: 'info', title: 'new', message: 'z' }]); // stays on the sign-in log
    expect(document.getElementById('events-list')?.textContent).toContain('anna signed out');
    /** @type {HTMLElement} */ (document.querySelector('[data-filter="all"]')).click();
    expect(document.getElementById('events-list')?.textContent).toContain('new');
  });
});
