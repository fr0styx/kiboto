/** SET-03: the Security and Notifications tabs load an administrator's set-up for administrators only. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  loadAccountPane,
  loadBackupExtras,
  loadSecurityPane,
  loadNotificationsPane,
  loadConnectionsPane,
} from '../components/management/admin-panes.js';
import '../route-access.js';
import { KibotoEventBus } from '../event-bus.js';
import { fetchAndRenderSecurityPosture } from '../components/management/security.js';
import { fetchAndRenderNotificationConfig } from '../components/management/notifications.js';
import { renderApiTokens } from '../components/settings.js';
import { renderGuardPanel } from '../components/guard-panel.js';
import { renderFileActivity } from '../components/file-activity.js';
import { renderSsoPanel, renderLdapPanel } from '../components/sso.js';
import { installMyData } from '../components/management/user-data.js';
import { renderPushCard } from '../components/push-card.js';

vi.mock('../components/management/security.js', () => ({ fetchAndRenderSecurityPosture: vi.fn() }));
vi.mock('../components/management/notifications.js', () => ({ fetchAndRenderNotificationConfig: vi.fn() }));
vi.mock('../components/settings.js', () => ({ renderApiTokens: vi.fn() }));
vi.mock('../components/guard-panel.js', () => ({ renderGuardPanel: vi.fn() }));
vi.mock('../components/file-activity.js', () => ({ renderFileActivity: vi.fn() }));
vi.mock('../components/sso.js', () => ({ renderSsoPanel: vi.fn(), renderLdapPanel: vi.fn() }));
vi.mock('../components/management/user-data.js', () => ({ installMyData: vi.fn() }));
vi.mock('../components/users.js', () => ({ loadAccountParts: vi.fn() }));
vi.mock('../components/management/home-assistant.js', () => ({ loadHomeAssistantCard: vi.fn() }));
vi.mock('../components/management/fleet.js', () => ({ loadFleetCard: vi.fn() }));
vi.mock('../components/push-card.js', () => ({ renderPushCard: vi.fn() }));
vi.mock('../components/management/connections.js', () => ({ renderRedfishCard: vi.fn() }));

const flush = () => new Promise((r) => setTimeout(r, 0));
const ADMIN_LOADERS = [fetchAndRenderSecurityPosture, renderGuardPanel, renderFileActivity]; // sign-in cards moved to Connections (SET-23)

describe('the Security and Notifications tabs (SET-03)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <div id="mgmt-pane-security"><div id="advisor" data-admin-only></div><div id="my-data"></div></div>
      <div id="mgmt-pane-notifications"><div id="channels" data-admin-only></div><div id="push"></div></div>
      <div id="mgmt-pane-account"><div id="api" data-admin-only></div><div id="pwd"></div></div>`;
  });

  it('a family member gets their own things and nothing of the set-up', async () => {
    KibotoEventBus.emit('session:user', { scopes: ['shares:read', 'shares:user_write', 'system:view'] });
    expect(loadSecurityPane()).toBe(false);
    expect(loadNotificationsPane()).toBe(false);
    await flush();
    for (const loader of [...ADMIN_LOADERS, fetchAndRenderNotificationConfig]) expect(loader).not.toHaveBeenCalled();
    expect(installMyData).not.toHaveBeenCalled(); // your data moved to My account (SET-19)
    expect(renderPushCard).toHaveBeenCalledTimes(1);
    expect(document.getElementById('advisor').hidden).toBe(true);
    expect(document.getElementById('channels').hidden).toBe(true);
    expect(document.getElementById('push').hidden).toBe(false);
  });

  it('an administrator gets both', async () => {
    KibotoEventBus.emit('session:user', { scopes: ['*'] });
    expect(loadSecurityPane()).toBe(true);
    expect(loadNotificationsPane()).toBe(true);
    await flush();
    for (const loader of [...ADMIN_LOADERS, fetchAndRenderNotificationConfig]) expect(loader).toHaveBeenCalledTimes(1);
    expect(renderApiTokens).not.toHaveBeenCalled(); // API keys moved to My account (SET-19)
    expect(renderPushCard).toHaveBeenCalledTimes(1);
    expect(document.getElementById('advisor').hidden).toBe(false);
  });
});

describe('My account (SET-19, decision X4)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML =
      '<div id="mgmt-pane-account"><div id="api" data-admin-only></div><div id="pwd"></div></div>';
  });

  it('every role gets their own sign-in things and data; only an administrator the API keys', async () => {
    const { loadAccountParts } = await import('../components/users.js');
    KibotoEventBus.emit('session:user', { scopes: ['shares:read', 'system:view'] });
    expect(loadAccountPane()).toBe(false);
    await flush();
    expect(loadAccountParts).toHaveBeenCalledTimes(1);
    expect(installMyData).toHaveBeenCalledTimes(1);
    expect(renderApiTokens).not.toHaveBeenCalled();
    expect(document.getElementById('api').hidden).toBe(true);
    expect(document.getElementById('pwd').hidden).toBe(false);
    vi.clearAllMocks();
    KibotoEventBus.emit('session:user', { scopes: ['*'] });
    expect(loadAccountPane()).toBe(true);
    await flush();
    expect(renderApiTokens).not.toHaveBeenCalled(); // the keys live on Connections now (SET-23)
  });
});

describe('cards moved from Network (SET-24)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('Home Assistant, API tokens, sign-in and Redfish load with Connections, for administrators only (SET-23)', async () => {
    const { loadHomeAssistantCard } = await import('../components/management/home-assistant.js');
    const { renderRedfishCard } = await import('../components/management/connections.js');
    document.body.innerHTML =
      '<div id="mgmt-pane-connections"><p class="conn-admins"></p><div id="notif-ha-grid" data-admin-only></div></div>';
    KibotoEventBus.emit('session:user', { scopes: ['system:view'] });
    expect(loadConnectionsPane()).toBe(false);
    await flush();
    for (const f of [loadHomeAssistantCard, renderApiTokens, renderSsoPanel, renderLdapPanel, renderRedfishCard])
      expect(f).not.toHaveBeenCalled();
    expect(/** @type {HTMLElement} */ (document.querySelector('.conn-admins')).hidden).toBe(false);
    KibotoEventBus.emit('session:user', { scopes: ['*'] });
    expect(loadConnectionsPane()).toBe(true);
    await flush();
    for (const f of [loadHomeAssistantCard, renderApiTokens, renderSsoPanel, renderLdapPanel, renderRedfishCard])
      expect(f).toHaveBeenCalledTimes(1);
    expect(/** @type {HTMLElement} */ (document.querySelector('.conn-admins')).hidden).toBe(true);
    loadNotificationsPane();
    await flush();
    expect(loadHomeAssistantCard).toHaveBeenCalledTimes(1); // not again from Notifications
  });

  it("My account's button opens Connections", () => {
    document.body.innerHTML = '<div id="mgmt-pane-account"><button id="acc-open-connections"></button></div>';
    const open = vi.fn();
    /** @type {any} */ (window).openManagementSection = open;
    loadAccountPane();
    /** @type {HTMLElement} */ (document.getElementById('acc-open-connections')).click();
    expect(open).toHaveBeenCalledWith('mgmt-pane-connections');
  });

  it('your other Kiboto boxes load with Backup', async () => {
    const { loadFleetCard } = await import('../components/management/fleet.js');
    document.body.innerHTML = '';
    expect(loadBackupExtras()).toBe(false);
    document.body.innerHTML = '<div id="backup-fleet-grid"></div>';
    expect(loadBackupExtras()).toBe(true);
    await flush();
    expect(loadFleetCard).toHaveBeenCalledTimes(1);
  });
});
