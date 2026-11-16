import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { api } from '../api.js';
import { appsDetailsOn, saveAppsDetails } from '../components/apps-details-pref.js';
import { applyAppsDetails, householdMenu } from '../components/containers-manager.js';
import { buildContainerRowInner } from '../components/docker-table.js';

beforeEach(() => {
  localStorage.clear();
  /** @type {any} */ (globalThis).kibotoUser = null;
});
afterEach(() => vi.restoreAllMocks());

describe('the Apps window: a simple view, and Docker details per person (SET-25 Apps 3/4)', () => {
  it('details are off by default, on for someone with Advanced, and the account wins', () => {
    expect(appsDetailsOn(null)).toBe(false);
    expect(appsDetailsOn({ preferences: { advanced: true } })).toBe(true);
    expect(appsDetailsOn({ preferences: { advanced: true, apps_details: false } })).toBe(false);
    localStorage.setItem('kiboto_apps_details', '1');
    expect(appsDetailsOn({ preferences: {} })).toBe(true);
  });

  it('saving keeps it in the browser and the account', () => {
    const put = vi.spyOn(api, 'put').mockResolvedValue({});
    expect(saveAppsDetails(true)).toBe(false); // nobody signed in: the browser only
    expect(localStorage.getItem('kiboto_apps_details')).toBe('1');
    const user = { preferences: {} };
    /** @type {any} */ (globalThis).kibotoUser = user;
    expect(saveAppsDetails(false)).toBe(true);
    expect(user.preferences.apps_details).toBe(false);
    expect(put).toHaveBeenCalledWith('/api/auth/me/preferences', { apps_details: false });
  });

  it('the switch sets the simple view on the window', () => {
    document.body.innerHTML = '<div id="containers-manager-window"><input type="checkbox" id="cw-details-toggle"></div>';
    applyAppsDetails(false);
    expect(document.getElementById('containers-manager-window')?.classList.contains('cw-simple')).toBe(true);
    applyAppsDetails(true);
    expect(document.getElementById('containers-manager-window')?.classList.contains('cw-simple')).toBe(false);
    expect(/** @type {HTMLInputElement} */ (document.getElementById('cw-details-toggle')).checked).toBe(true);
  });

  it('the menu is the household one, in order, and presses the row action', () => {
    document.body.innerHTML = '<div><button data-action="restart" id="r"></button><button data-action="stop" id="s"></button><button data-action="start" id="g"></button><button id="more"></button></div>';
    const more = /** @type {HTMLElement} */ (document.getElementById('more'));
    const running = householdMenu({ id: 'x', name: 'jellyfin', state: 'running', status: 'Up 2 hours' }, more, true);
    expect(running.map((i) => i.label)).toEqual(['Restart', 'Stop', 'Update', 'Back up now', 'Show the log', 'Details', 'Remove']);
    expect(running.at(-1)?.destructive).toBe(true);
    const restart = vi.fn();
    document.getElementById('r')?.addEventListener('click', restart);
    running[0].onClick();
    expect(restart).toHaveBeenCalled();
    const stopped = householdMenu({ id: 'y', name: 'old', state: 'exited', status: 'Exited (0)' }, more, false);
    expect(stopped[0].label).toBe('Start');
    expect(stopped.map((i) => i.label)).not.toContain('Update');
  });

  it('a running app with a web page gets Open', () => {
    const cells = buildContainerRowInner({ id: 'abc', name: 'jellyfin', state: 'running', status: 'Up', webui_url: 'http://[HOST]:8096/', primary_port: 8096, ports: [] }, 'nas.local');
    const tr = document.createElement('tr');
    tr.innerHTML = cells;
    const open = /** @type {HTMLAnchorElement} */ (tr.querySelector('.docker-open-cell a'));
    expect(open.getAttribute('href')).toBe('http://nas.local:8096/');
    expect(open.textContent).toBe('Open');
    const stopped = document.createElement('tr');
    stopped.innerHTML = buildContainerRowInner({ id: 'd', name: 'x', state: 'exited', status: 'Exited', webui_url: 'http://[HOST]:1/', ports: [] }, 'nas.local');
    expect(stopped.querySelector('.docker-open-cell a')).toBeNull();
  });
});
