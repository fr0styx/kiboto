/**
 * The Security and Notifications tabs hold an administrator's set-up beside each person's own
 * things (SET-03). For anyone but an administrator the set-up is not drawn and not asked for;
 * what is theirs (their data, their devices) loads for everyone.
 */
import { hideAdminOnly } from '../../admin-only.js';
import { fetchAndRenderSecurityPosture } from './security.js';
import { fetchAndRenderNotificationConfig } from './notifications.js';

/** @returns {boolean} true when the administrator's part was loaded too */
export function loadSecurityPane() {
  const adminToo = !hideAdminOnly(document.getElementById('mgmt-pane-security'));
  if (adminToo) {
    import('../guard-panel.js').then((m) => m.renderGuardPanel()).catch(() => {});
    import('../file-activity.js').then((m) => m.renderFileActivity()).catch(() => {}); // FEAT-12
    fetchAndRenderSecurityPosture();
  }
  return adminToo;
}

/** My account (SET-19, decision X4): password, two-step sign-in and passkeys, signed-in devices and
 *  your data for every role; for administrators a way to the API keys on Connections (SET-23).
 *  @returns {boolean} true when the administrator's part was loaded too */
export function loadAccountPane() {
  const adminToo = !hideAdminOnly(document.getElementById('mgmt-pane-account'));
  import('../users.js').then((m) => m.loadAccountParts()).catch(() => {});
  import('./user-data.js').then((m) => m.installMyData()).catch(() => {}); // your data (B8)
  const open = document.getElementById('acc-open-connections'); // API keys live on Connections (SET-23)
  if (open) open.onclick = () => /** @type {any} */ (window).openManagementSection?.('mgmt-pane-connections');
  return adminToo;
}

/** Connections (SET-23, Settings decision 8): Home Assistant, API tokens, single sign-on and LDAP,
 *  Redfish. An Advanced page, for administrators.
 *  @returns {boolean} true when the administrator's part was loaded */
export function loadConnectionsPane() {
  const pane = document.getElementById('mgmt-pane-connections');
  const adminToo = !hideAdminOnly(pane);
  const note = /** @type {HTMLElement | null} */ (pane?.querySelector('.conn-admins') || null);
  if (note) note.hidden = adminToo;
  if (!adminToo) return false;
  import('./home-assistant.js').then((m) => m.loadHomeAssistantCard()).catch(() => {});
  import('../settings.js').then((m) => m.renderApiTokens && m.renderApiTokens()).catch(() => {});
  import('../sso.js').then((m) => { m.renderSsoPanel(); m.renderLdapPanel(); }).catch(() => {});
  import('./connections.js').then((m) => m.renderRedfishCard()).catch(() => {});
  return true;
}

/** @returns {boolean} true when the administrator's part was loaded too */
export function loadNotificationsPane() {
  const adminToo = !hideAdminOnly(document.getElementById('mgmt-pane-notifications'));
  if (adminToo) fetchAndRenderNotificationConfig();
  import('../push-card.js').then((m) => m.renderPushCard()).catch(() => {});
  return adminToo;
}

/** Backup's extras: your other Kiboto boxes, whose main use is a buddy backup (moved from Network, SET-24). */
export function loadBackupExtras(doc = document) {
  if (!doc.getElementById('backup-fleet-grid')) return false;
  import('./fleet.js').then((m) => m.loadFleetCard()).catch(() => {});
  import('../backup-verdict.js').then((m) => m.renderVerdict(doc.getElementById('backup-verdict-mount'))).catch(() => {}); // SET-21
  import('../backup-folders.js').then((m) => m.renderFolders(doc.getElementById('backup-verdict-mount'))).catch(() => {}); // Backup 5
  import('../restore-door.js')
    .then((m) => m.installRestoreDoor(doc.getElementById('backup-restore-mount'))) // SET-21 stage 2
    .then(() => import('../backup-needs.js'))
    .then((m) => m.applyNeeds(doc.getElementById('mgmt-pane-backups'))) // rights (B9): the door and the settings file
    .catch(() => {});
  const add = doc.getElementById('btn-add-copy');
  if (add) add.onclick = () => import('../protect-nas.js').then((m) => m.openProtectGuide()).catch(() => {}); // SET-21 stage 3
  return true;
}

