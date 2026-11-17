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

  it("Kiboto's own containers are left out of the simple list, and come back with the details", async () => {
    const { renderContainersWindowTable, renderAppsSummary } = await import('../components/containers-manager.js');
    document.body.innerHTML = '<div id="containers-manager-window"><div id="cw-status-chip"><span id="cw-stat-daemon"></span></div><table><tbody id="cw-docker-containers-tbody"></tbody></table></div>';
    const list = [
      { id: 'k', name: 'kiboto', state: 'running', status: 'Up', kiboto_own: true, ports: [] },
      { id: 'j', name: 'jellyfin', state: 'running', status: 'Up', ports: [] },
    ];
    renderContainersWindowTable(list);
    renderAppsSummary();
    const names = () => [...document.querySelectorAll('#cw-docker-containers-tbody .btn-docker-name-link')].map((b) => b.textContent);
    expect(names()).toEqual(['jellyfin']);
    expect(document.getElementById('cw-stat-daemon')?.textContent).toContain('running');
    localStorage.setItem('kiboto_apps_details', '1');
    renderContainersWindowTable(list);
    expect(names().sort()).toEqual(['jellyfin', 'kiboto']);
  });

  it('Get apps: an installed app with a page offers Open; search comes first', async () => {
    const { installedContainer, appPageUrl, catalogCardHtml } = await import('../components/catalog-view.js');
    const app = { id: 'jf', name: 'Jellyfin', image: 'jellyfin/jellyfin:latest', category: 'media' };
    const box = { name: 'jellyfin', image: 'jellyfin/jellyfin:10.9', state: 'running', webui_url: 'http://[HOST]:8096/' };
    expect(installedContainer(app, [box])).toBe(box);
    expect(installedContainer({ id: 'x' }, [box])).toBeNull();
    expect(appPageUrl(box, 'nas.local')).toBe('http://nas.local:8096/');
    expect(appPageUrl({ ...box, state: 'exited' }, 'nas.local')).toBe('');
    expect(appPageUrl({ ...box, webui_url: 'javascript:alert(1)' }, 'nas.local')).toBe('');
    const card = document.createElement('div');
    card.innerHTML = catalogCardHtml(app, { installed: true, openUrl: 'http://nas.local:8096/' });
    expect(card.querySelector('a.catalog-open')?.getAttribute('href')).toBe('http://nas.local:8096/');
    expect(card.querySelector('.btn-deploy-app')).toBeNull();
    card.innerHTML = catalogCardHtml(app, { installed: true });
    expect(card.querySelector('.btn-deploy-app')?.textContent).toBe('Install again');
    const src = (await import('fs')).readFileSync((await import('path')).resolve(__dirname, '../components/containers-manager.js'), 'utf8');
    const head = src.slice(src.indexOf('<div class="cw-catalog-head">'));
    expect(head.indexOf('cw-catalog-search-input')).toBeLessThan(head.indexOf('cw-catalog-filter-pills'));
  });

  it("a stack's apps sit together and say which stack they are in", async () => {
    const { byStackThenName } = await import('../components/containers-manager.js');
    const list = [{ name: 'z-app' }, { name: 'web', stack: 'immich' }, { name: 'db', stack: 'immich' }, { name: 'a-app' }, { name: 'x', stack: 'arr' }];
    expect([...list].sort(byStackThenName).map((c) => c.name)).toEqual(['x', 'db', 'web', 'a-app', 'z-app']);
    const tr = document.createElement('tr');
    tr.innerHTML = buildContainerRowInner({ id: 'w', name: 'web', stack: 'immich', state: 'running', status: 'Up', ports: [] }, 'nas.local');
    expect(tr.querySelector('.cw-stack-note')?.textContent).toBe('In immich');
  });

  it('the simple view shows one row per app; the Docker details name each stack in a header row', async () => {
    const { renderContainersWindowTable, withStackHeads } = await import('../components/containers-manager.js');
    expect(withStackHeads([{ name: 'a' }])).toEqual([{ name: 'a' }]);
    expect(withStackHeads([{ name: 'x', stack: 'arr' }, { name: 'b' }]).map((c) => c.__stack ?? c.name)).toEqual(['arr', 'x', '', 'b']);
    document.body.innerHTML = '<div id="containers-manager-window"><table><tbody id="cw-docker-containers-tbody"></tbody></table></div>';
    const list = [
      { id: 'w', name: 'web', stack: 'immich', state: 'running', status: 'Up', ports: [] },
      { id: 'd', name: 'db', stack: 'immich', state: 'running', status: 'Up', ports: [] },
      { id: 'j', name: 'jellyfin', state: 'running', status: 'Up', ports: [] },
    ];
    localStorage.removeItem('kiboto_apps_details');
    renderContainersWindowTable(list);
    const tbody = /** @type {HTMLElement} */ (document.getElementById('cw-docker-containers-tbody'));
    const rows = () => [...tbody.children].map((tr) => (tr.classList.contains('cw-stack-head') ? `# ${tr.textContent}` : tr.querySelector('.btn-docker-name-link')?.textContent));
    // Apps decision 2: the two containers of immich are one app
    expect(rows()).toEqual(['immich', 'jellyfin']);
    expect(tbody.classList.contains('cw-has-heads')).toBe(false);
    const appRow = /** @type {HTMLElement} */ (tbody.querySelector('tr.cw-app-row'));
    expect(appRow.querySelector('.docker-status-text')?.textContent).toBe('2 parts');
    expect(appRow.querySelector('.cw-stack-note')).toBeNull();
    /** @type {HTMLElement} */ (appRow.querySelector('[data-action="more-sheet"]')).click();
    expect(document.body.textContent).toContain('Part: db');
    /** @type {HTMLElement} */ (appRow.querySelector('.btn-docker-name-link')).click();
    renderContainersWindowTable(list); // a redraw keeps one row per app
    expect(rows()).toEqual(['immich', 'jellyfin']);
    localStorage.setItem('kiboto_apps_details', '1');
    renderContainersWindowTable(list);
    expect(rows()).toEqual(['# immich', 'db', 'web', '# Other apps', 'jellyfin']);
    expect(tbody.querySelector('.cw-stack-head th')?.getAttribute('scope')).toBe('colgroup');
    localStorage.removeItem('kiboto_apps_details');
  });
});

