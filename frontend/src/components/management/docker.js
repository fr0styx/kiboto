/**
 * Mission Control: Docker containers table, app catalog, deploy, prune, sources and sideload.
 * Split out of management.js (ARCH-1); management.js re-exports everything here.
 */
import { serverSaid } from '../../server-text.js';
import { ZettEventBus } from '../../event-bus.js';
import { bringToFront, DockManager, makeDraggable, showDockToast } from '../dock.js';
import { api } from '../../api.js';
import { showToast, showConfirmToast, showDangerConfirm } from '../../toast.js';
import { escapeHtml, copyTextToClipboard, copyText } from '../../utils.js';
import { t } from '../../i18n.js';
import { formatBytes as formatSize } from '../../format.js';
import { setDeployButtonTone } from '../management.js';

// An icon next to translated words: screen readers skip it and the words stay plain (UX-35)
const ico = (e) => `<span aria-hidden="true">${e}</span>`;
// A value set in bold inside translated words: the value escaped, the words from the locale
const bold = (v) => `<strong>${escapeHtml(String(v))}</strong>`;
import { renderShareFolders, shareFolderPicks } from '../share-folder-picker.js';
import { setIconLabel } from '../../ui/primitives.js';
import '../../styles/docker-lazy.css'; // its dialogs' own sheet loads with this code (NUX-15)

let _storageRoot = '/mnt/user/appdata'; // until the server says where this host keeps app data
function portBusy(port, check) {
  const p = escapeHtml(String(port));
  return check.in_use_by
    ? t('dk.port_busy_by', 'Port {port} is already in use by {name}. Choose a free port before installing.', { port: p, name: escapeHtml(check.in_use_by) })
    : t('dk.port_busy', 'Port {port} is already in use. Choose a free port before installing.', { port: p });
}

export function showDeployCredentials(successBox, data, hostPort) {
  if (!successBox || !successBox.parentElement) return;
  successBox.parentElement.querySelector('.adm-credentials')?.remove();
  const c = data.credentials || {};
  const rows = [];
  if (data.has_webui === false) rows.push([t('catalog.connect_to', 'Connect to'), hostPort]);
  if (c.user) rows.push([t('catalog.cred_user', 'User'), c.user]);
  if (c.password) rows.push([t('catalog.cred_password', 'Password'), c.password]);
  if (!rows.length && !c.note) return;
  const box = document.createElement('div');
  box.className = 'adm-credentials';
  box.innerHTML = `<div class="adm-cred-title">🔑 ${escapeHtml(t('catalog.cred_title', 'Sign-in details'))}</div>` +
    rows.map(([label, value], i) => `<div class="adm-cred-row"><span class="adm-cred-label">${escapeHtml(label)}</span><code class="adm-cred-val">${escapeHtml(value)}</code><button type="button" class="adm-cred-copy" data-i="${i}" aria-label="${escapeHtml(t('catalog.copy', 'Copy'))} ${escapeHtml(label)}">${escapeHtml(t('catalog.copy', 'Copy'))}</button></div>`).join('') +
    (c.note ? `<div class="adm-cred-note">${escapeHtml(c.note)}</div>` : '') +
    (c.password && /[A-Za-z0-9_-]{20,}/.test(c.password) ? `<div class="adm-cred-note">${escapeHtml(t('catalog.cred_saved', 'Saved in a hidden file in the app\'s folder, so a reinstall keeps it.'))}</div>` : '');
  box.addEventListener('click', async (e) => {
    const btn = e.target instanceof Element ? e.target.closest('.adm-cred-copy') : null;
    if (!btn) return;
    try {
      await copyText(rows[Number(btn.dataset.i)][1]);
      showToast(t('common.copied', 'Copied to clipboard!'), 'success');
    } catch (_) {
      showToast(t('toast.failed_to_copy', 'Failed to copy'), 'error');
    }
  });
  successBox.insertAdjacentElement('afterend', box);
}

/** UX-18: the usual port is taken, so another is used; the Advanced section opens to show it. */
export function portTakenHtml(defaultPort, suggestedPort, inUseBy) {
  const advanced = document.getElementById('adm-advanced');
  if (advanced) advanced.open = true;
  const msg = inUseBy
    ? t('catalog.install_port_taken_by', 'Port {port} is already used by {app}, so this app uses port {free}.', { port: defaultPort, app: inUseBy, free: suggestedPort })
    : t('catalog.install_port_taken', 'Port {port} is already in use, so this app uses port {free}.', { port: defaultPort, free: suggestedPort });
  return `<span style="color:var(--warn, #f5a623); font-weight:bold;">⚠️</span> ${escapeHtml(msg)}`;
}

export async function openAppDeployModal(appId) {
  let modal = document.getElementById('app-deploy-modal-overlay');
  if (!modal) {
    const modalHtml = `
      <div id="app-deploy-modal-overlay" class="smart-modal-backdrop" style="display:none;">
        <div id="app-deploy-modal-window" class="smart-modal-window app-deploy-window dkd-size" style="display: flex;">
          <div class="smart-modal-header dkd-x" id="adm-header" style="display: flex;">
            <div class="dkd-row">
              <span class="dkd-fs18" id="adm-icon">📦</span>
              <span class="dkd-fs13-bold-strong" id="adm-title">${t('catalog.install_app', 'Install an app')}</span>
            </div>
            <div class="os-window-controls dkd-row-2">
              <button class="win-btn min-btn" id="adm-min-btn" title="${t('ui.minimize_to_dock', 'Minimize to Dock')}" aria-label="${t('window.minimize', 'Minimize')}"></button>
              <button class="win-btn close-btn" id="adm-close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
            </div>
          </div>

          <!-- View 1: Configuration View -->
          <div class="dkd-grow" id="adm-view-config" style="display: flex;">
            <div class="dkd-xs-box" id="adm-conflict-banner"></div>
            
            <!-- Pre-existing Container Action Choice Box -->
            <div id="adm-existing-box" style="display:none; padding:11px 13px; border-radius:6px; background:rgba(245, 166, 35, 0.09); border:1px solid rgba(245, 166, 35, 0.35); flex-direction:column; gap:8px;">
              <div class="dkd-row-3">
                <div style="display:flex; align-items:center; gap:6px; color:var(--warn, #f5a623); font-weight:700; font-size:var(--kb-fs-xs);">
                  <span aria-hidden="true">⚠️</span> <span id="adm-existing-title">${t('catalog.existing_title', 'This app is already installed')}</span>
                </div>
                <span class="dkd-xs-bold-mono-box" id="adm-existing-status-badge">${t('catalog.state_running', 'Running')}</span>
              </div>
              <div class="dkd-xs-soft" id="adm-existing-desc">
                ${t('catalog.existing_desc_generic', 'An app with this name or port is already on this server. Choose what to do:')}
              </div>
              <div class="dkd-grid">
                <button type="button" id="adm-choice-replace-btn" class="btn-pill-toggle is-danger" style="text-align: center; color: var(--lt-t-ff8080ff, #ff8080);">
                  🔄 ${t('catalog.replace', 'Replace the one there')}
                </button>
                <button type="button" id="adm-choice-new-btn" class="btn-pill-toggle" style="text-align: center; border: 2px solid var(--ok2, #33cdb8); background: rgba(51, 205, 184, 0.18); color: var(--ok2, #33cdb8);">
                  ➕ ${t('catalog.alongside', 'Install another copy')}
                </button>
              </div>
            </div>

            <div>
              <label for="adm-name-input" class="adm-label">${t('catalog.install_name', 'Name')}</label>
              <input type="text" id="adm-name-input" class="tz-text-input dkd-xs">
            </div>
            <div>
              <label for="adm-storage-input" class="adm-label">${t('catalog.install_folder', 'Folder for its data')}</label>
              <input type="text" id="adm-storage-input" value="/mnt/user/appdata" class="tz-text-input dkd-xs">
              <div class="adm-hint">${t('catalog.install_folder_hint', 'Settings and files the app keeps are stored in a folder of its own here.')}</div>
            </div>
            <div id="adm-share-folders" class="adm-share-folders" hidden></div>
            <!-- UX-18: the technical part stays out of the way -->
            <details id="adm-advanced" class="adm-advanced">
              <summary>${t('catalog.install_advanced', 'Advanced: port and Docker Compose')}</summary>
              <div class="dkd-col">
                <div>
                  <label for="adm-port-input" class="adm-label">${t('catalog.install_port', 'Port on this server')}</label>
                  <input type="number" id="adm-port-input" class="tz-text-input dkd-xs-mono">
                </div>
                <div>
                  <div class="dkd-row-4">
                    <span class="adm-label dkd-x-2">${t('catalog.install_compose', 'Docker Compose definition')}</span>
                    <div class="dkd-row-5">
                      <button class="btn-pill-toggle" id="adm-copy-btn">${ico('📋')} ${t('ci.copy_yaml', 'Copy YAML')}</button>
                      <button class="btn-pill-toggle" id="adm-download-btn">${ico('⬇️')} ${t('dk.download', 'Download')}</button>
                    </div>
                  </div>
                  <pre id="adm-compose-pre" style="margin:0; background:var(--lt-b-091213ff, #091213); border:1px solid var(--kb-line-10); border-radius:6px; padding:10px; max-height:200px; overflow:auto; font-family:var(--font-mono, monospace); font-size:var(--kb-fs-xs); color:var(--kb-text); line-height:1.45;"></pre>
                </div>
              </div>
            </details>
          </div>

          <!-- View 2: Live Deployment Progress View -->
          <div class="dkd-grow-2" id="adm-view-progress" style="display: none;">
            <div class="dkd-row-3">
              <div class="dkd-row-6">
                <span class="dkd-fs22" id="adm-progress-spinner" style="display: inline-block;">⚙️</span>
                <div>
                  <div class="dkd-fs13-bold-strong-2" id="adm-progress-title">${t('catalog.installing', 'Installing the app...')}</div>
                  <div class="dkd-xs-muted" id="adm-progress-status-text">${t('catalog.preparing', 'Getting its folders ready...')}</div>
                </div>
              </div>
              <div id="adm-progress-pct-badge" style="font-size:13px; font-weight:800; font-family:var(--font-mono, monospace); color:var(--lt-ink-brand, var(--accent-cyan, #33cdb8)); background:var(--lt-b-33cdb814, rgba(51,205,184,0.08)); padding:3px 9px; border-radius:6px; border:1px solid var(--lt-r-33cdb833, rgba(51,205,184,0.2));">0%</div>
            </div>

            <!-- Stylized Progress Bar -->
            <div class="dkd-box">
              <div id="adm-progress-bar-fill" style="height:100%; width:0%; background:linear-gradient(90deg, var(--brand, #33cdb8), var(--ok2, #33cdb8)); transition:width 0.25s ease; box-shadow:0 0 10px rgba(51,205,184,0.5);"></div>
            </div>

            <!-- Real-time Activity Log Terminal -->
            <div class="dkd-x-3">
              <div class="dkd-xs-bold-muted">${t('catalog.install_log', 'What is happening')}</div>
              <div id="adm-deploy-logs" style="background:var(--lt-b-060d0eff, #060d0e); border:1px solid var(--kb-line-10); border-radius:6px; height:160px; overflow-y:auto; padding:10px; font-family:var(--font-mono, monospace); font-size:var(--kb-fs-xs); line-height:1.5; color:var(--kb-text-soft);">
                <div class="dkd-muted">${t('catalog.waiting', 'Starting...')}</div>
              </div>
            </div>

            <!-- Success Callout -->
            <div id="adm-success-box" style="display:none; padding:12px 14px; background:rgba(51,205,184,0.12); border:1px solid var(--ok2, #33cdb8); border-radius:6px; align-items:center; justify-content:space-between; gap:12px;">
              <div>
                <div style="font-weight:700; color:var(--ok2, #33cdb8); font-size:var(--kb-fs-xs);">🚀 ${t('catalog.live', 'The app is running')}</div>
                <div class="dkd-xs-soft-2" id="adm-success-msg">${t('catalog.live_desc', 'It is installed and started.')}</div>
              </div>
              <a id="adm-webui-launch-btn" href="#" target="_blank" rel="noopener noreferrer" class="btn-pill-toggle" style="background:var(--ok2, #33cdb8); color:var(--accent-contrast-fg); font-weight:700; font-size:var(--kb-fs-xs); padding:6px 14px; text-decoration:none; display:inline-flex; align-items:center; gap:6px;">
                🌐 ${t('catalog.open_app', 'Open the app')} ↗
              </a>
            </div>
          </div>

          <!-- Footer for Config View -->
          <div class="dkd-box-2" id="adm-footer-config" style="display: flex;">
            <button class="btn-pill-toggle" id="adm-cancel-btn">${t('common.cancel', 'Cancel')}</button>
            <button class="btn-pill-toggle is-primary" id="adm-deploy-confirm-btn">
              ${t('ui.deploy_launch_container', 'Install')}
            </button>
          </div>

          <!-- Footer for Progress View -->
          <div class="dkd-box-2" id="adm-footer-progress" style="display: none;">
            <button class="btn-pill-toggle" id="adm-back-to-config-btn" style="display: none;">${ico('←')} ${t('dk.reconfigure', 'Change settings')}</button>
            <div class="dkd-grow-3"></div>
            <button class="btn-pill-toggle is-primary" id="adm-progress-close-btn" style="display: none;">${ico('✓')} ${t('common.done', 'Done')}</button>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    modal = document.getElementById('app-deploy-modal-overlay');

    const win = document.getElementById('app-deploy-modal-window');
    const header = document.getElementById('adm-header');
    if (win && header) {
      makeDraggable(win, header, 'app-deploy');
    }
    if (win) {
      win.addEventListener('pointerdown', () => {
        bringToFront(win);
      }, { capture: true });
    }

    const minBtn = document.getElementById('adm-min-btn');
    if (minBtn) {
      minBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (DockManager) {
          DockManager.minimize('app-deploy');
        } else {
          modal.classList.add('window-minimized');
          modal.style.display = 'none';
        }
      });
    }

    document.getElementById('adm-close-btn').addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (modal._isDeploying) {
        if (DockManager) {
          DockManager.minimize('app-deploy');
        } else {
          modal.classList.add('window-minimized');
          modal.style.display = 'none';
        }
        showToast(t('toast.deploying_in_background_click_dock_icon', '{activeAppId} is still installing. Its window is in the dock.', { activeAppId: modal._activeAppId || 'app' }), 'info');
      } else {
        if (modal._close) modal._close();
      }
    });

    document.getElementById('adm-cancel-btn').addEventListener('click', (e) => {
      e.preventDefault();
      if (modal._close) modal._close();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('open') && !modal.classList.contains('window-minimized')) {
        if (modal._isDeploying) {
          if (DockManager) DockManager.minimize('app-deploy');
          else modal.classList.add('window-minimized');
          showToast(t('toast.deploying_in_background_reopen_from_dock', `Deploying in background. Reopen from Dock anytime.`), 'info');
        } else if (modal._close) {
          modal._close();
        }
      }
    });
  }

  modal._close = () => {
    modal._isDeploying = false;
    modal.classList.remove('open', 'window-minimized');
    modal.style.display = 'none';
    if (DockManager) {
      DockManager.unregister('app-deploy');
    }
    const vc = document.getElementById('adm-view-config');
    const vp = document.getElementById('adm-view-progress');
    const fc = document.getElementById('adm-footer-config');
    const fp = document.getElementById('adm-footer-progress');
    if (vc) vc.style.display = 'flex';
    if (vp) vp.style.display = 'none';
    if (fc) fc.style.display = 'flex';
    if (fp) fp.style.display = 'none';
  };

  // Ensure config view is visible by default and open modal
  modal._activeAppId = appId;
  modal._isDeploying = false;
  modal.classList.remove('window-minimized');
  modal.classList.add('open');
  modal.style.display = 'flex';

  const win = document.getElementById('app-deploy-modal-window');
  if (win) {
    win.classList.remove('window-minimized');
    win.style.removeProperty('display');
    bringToFront(win);
  }

  // Register in DockManager
  if (DockManager) {
    if (!DockManager.windows['app-deploy']) {
      DockManager.register('app-deploy', modal, '#i-chip', t('catalog.install_title', 'Install {name}', { name: appId }), false);
    } else {
      DockManager.windows['app-deploy'].title = t('catalog.install_title', 'Install {name}', { name: appId });
      DockManager.restore('app-deploy');
    }
  }

  modal.style.display = 'flex';

  const viewConfig = document.getElementById('adm-view-config');
  const viewProgress = document.getElementById('adm-view-progress');
  const footerConfig = document.getElementById('adm-footer-config');
  const footerProgress = document.getElementById('adm-footer-progress');
  if (viewConfig) viewConfig.style.display = 'flex';
  if (viewProgress) viewProgress.style.display = 'none';
  if (footerConfig) footerConfig.style.display = 'flex';
  if (footerProgress) footerProgress.style.display = 'none';

  let replaceExisting = false;
  let defaultContainerName = appId;
  let suggestedContainerName = appId;
  let defaultPort = 8080;
  let suggestedPort = 8080;
  let existingContainerInfo;

  const deployConfirmBtn = document.getElementById('adm-deploy-confirm-btn');
  const banner = document.getElementById('adm-conflict-banner');
  const existingBox = document.getElementById('adm-existing-box');
  const existingBadge = document.getElementById('adm-existing-status-badge');
  const existingDesc = document.getElementById('adm-existing-desc');
  const choiceReplaceBtn = document.getElementById('adm-choice-replace-btn');
  const choiceNewBtn = document.getElementById('adm-choice-new-btn');
  const nameInput = document.getElementById('adm-name-input');
  const portInput = document.getElementById('adm-port-input');
  const storageInput = document.getElementById('adm-storage-input');
  // the host's own place for app data (TrueNAS, plain Linux), not always Unraid's (NUX-12)
  Promise.resolve()
    .then(() => api.get('/api/docker/catalog/defaults'))
    .then(
    (d) => {
      if (!d || !d.storage_root) return;
      const box = /** @type {HTMLInputElement | null} */ (storageInput);
      if (box && box.value === _storageRoot) box.value = d.storage_root;
      _storageRoot = d.storage_root;
    },
    () => {},
  );
  const composePre = document.getElementById('adm-compose-pre');
  const shareMount = document.getElementById('adm-share-folders');
  const title = document.getElementById('adm-title');

  if (existingBox) existingBox.style.display = 'none';
  if (choiceReplaceBtn) {
    choiceReplaceBtn.style.border = '1px solid rgba(235, 87, 87, 0.4)';
    choiceReplaceBtn.style.background = 'rgba(235, 87, 87, 0.12)';
    choiceReplaceBtn.style.opacity = '0.75';
    choiceReplaceBtn.style.boxShadow = 'none';
  }
  if (choiceNewBtn) {
    choiceNewBtn.style.border = '2px solid var(--ok2, #33cdb8)';
    choiceNewBtn.style.background = 'rgba(51, 205, 184, 0.18)';
    choiceNewBtn.style.opacity = '1';
    choiceNewBtn.style.boxShadow = '0 0 8px rgba(51,205,184,0.3)';
  }

  if (nameInput) {
    nameInput.value = appId;
    nameInput.style.borderColor = '';
  }
  if (portInput) {
    portInput.value = 8080;
    portInput.style.borderColor = '';
  }

  if (deployConfirmBtn) {
    deployConfirmBtn.disabled = false;
    deployConfirmBtn.style.opacity = '1';
    deployConfirmBtn.style.pointerEvents = 'auto';
    deployConfirmBtn.textContent = t('ui.deploy_launch_container', 'Install');
    setDeployButtonTone(deployConfirmBtn, 'brand');
  }

  title.textContent = t('catalog.install_title', 'Install {name}', { name: appId });
  const advanced = document.getElementById('adm-advanced');
  if (advanced) advanced.open = false;
  banner.replaceChildren(Object.assign(document.createElement('span'), { className: 'muted', textContent: t('catalog.checking', 'Checking the ports and apps already here...') }));
  banner.style.background = 'rgba(255,255,255,0.04)';
  banner.style.border = '1px solid rgba(255,255,255,0.08)';

  try {
    const resolveData = await api.get(`/api/docker/catalog/${appId}/resolve`);
    defaultPort = resolveData.default_port || 8080;
    suggestedPort = resolveData.suggested_port || defaultPort;
    existingContainerInfo = resolveData.existing_container;
    suggestedContainerName = resolveData.suggested_container_name || appId;
    defaultContainerName = (existingContainerInfo && existingContainerInfo.name) ? existingContainerInfo.name : appId;

    if (existingContainerInfo) {
      if (existingBox) existingBox.style.display = 'flex';
      const isRunning = existingContainerInfo.state === 'running';
      if (existingBadge) {
        existingBadge.textContent = isRunning ? t('catalog.state_running', 'Running') : t('catalog.state_stopped', 'Stopped');
        existingBadge.style.color = isRunning ? 'var(--ok2, #33cdb8)' : 'var(--muted)';
        existingBadge.style.background = isRunning ? 'rgba(51,205,184,0.15)' : 'rgba(255,255,255,0.08)';
      }
      if (existingDesc) {
        existingDesc.textContent = t('catalog.existing_desc', '{name} is already installed. Replace it, or install another copy next to it?', { name: existingContainerInfo.name }); // a name is text, never HTML
      }

      // Default to Deploy Alongside
      replaceExisting = false;
      if (nameInput) nameInput.value = suggestedContainerName;
      if (portInput) portInput.value = suggestedPort;

      if (resolveData.conflict_detected) {
        banner.style.background = 'rgba(245, 166, 35, 0.12)';
        banner.style.border = '1px solid var(--warn, #f5a623)';
        banner.innerHTML = portTakenHtml(defaultPort, suggestedPort, resolveData.in_use_by);
      } else {
        banner.style.background = 'rgba(51, 205, 184, 0.12)';
        banner.style.border = '1px solid var(--ok2, #33cdb8)';
        banner.innerHTML = `<span style="color:var(--ok2, #33cdb8); font-weight:bold;">${ico('✓')} ${t('dk.alongside_lead', 'Install alongside:')}</span> ${t('dk.alongside', 'Suggested name {name} on free port {port}.', { name: bold(suggestedContainerName), port: bold(suggestedPort) })}`;
      }
      if (deployConfirmBtn) setIconLabel(deployConfirmBtn, '🚀', t('ui.deploy_new_instance', 'Install a second copy'));
    } else if (resolveData.conflict_detected) {
      if (nameInput) nameInput.value = appId;
      if (portInput) portInput.value = suggestedPort;
      banner.style.background = 'rgba(245, 166, 35, 0.12)';
      banner.style.border = '1px solid var(--warn, #f5a623)';
      banner.innerHTML = portTakenHtml(defaultPort, suggestedPort, resolveData.in_use_by);
    } else {
      if (nameInput) nameInput.value = appId;
      if (portInput) portInput.value = suggestedPort;
      banner.style.background = 'rgba(51, 205, 184, 0.12)';
      banner.style.border = '1px solid var(--ok2, #33cdb8)';
      banner.innerHTML = `<span style="color:var(--ok2, #33cdb8); font-weight:bold;">✓ ${escapeHtml(t('catalog.install_ready', 'Ready to install'))}</span> ${escapeHtml(t('catalog.install_ready_detail', '{name} will open on port {port}.', { name: appId, port: suggestedPort }))}`;
    }
  } catch (e) {
    if (nameInput) nameInput.value = appId;
    if (portInput) portInput.value = 8080;
    banner.replaceChildren(Object.assign(document.createElement('span'), { className: 'muted', textContent: t('catalog.port_default', 'Using the usual port.') }));
  }

  function selectReplaceMode() {
    replaceExisting = true;
    if (nameInput) {
      nameInput.value = defaultContainerName;
      nameInput.style.borderColor = '';
    }
    if (portInput) {
      portInput.value = defaultPort;
      portInput.style.borderColor = '';
    }

    if (choiceReplaceBtn) {
      choiceReplaceBtn.style.border = '2px solid var(--err, #eb5757)';
      choiceReplaceBtn.style.background = 'rgba(235, 87, 87, 0.22)';
      choiceReplaceBtn.style.opacity = '1';
      choiceReplaceBtn.style.boxShadow = '0 0 8px rgba(235,87,87,0.4)';
    }
    if (choiceNewBtn) {
      choiceNewBtn.style.border = '1px solid rgba(51, 205, 184, 0.4)';
      choiceNewBtn.style.background = 'rgba(51, 205, 184, 0.1)';
      choiceNewBtn.style.opacity = '0.75';
      choiceNewBtn.style.boxShadow = 'none';
    }

    banner.style.background = 'rgba(235, 87, 87, 0.12)';
    banner.style.border = '1px solid var(--err, #eb5757)';
    banner.innerHTML = `<span style="color:var(--lt-t-ff8080ff, #ff8080); font-weight:bold;">${ico('⚠️')} ${t('dk.replace_lead', 'Stop & replace:')}</span> ${t('dk.replace_existing', 'The container {name} is stopped and replaced on port {port}. Saved data stays.', { name: bold(defaultContainerName), port: bold(defaultPort) })}`;

    if (deployConfirmBtn) {
      setIconLabel(deployConfirmBtn, '🔄', t('ui.stop_replace_launch', 'Replace and start'));
      setDeployButtonTone(deployConfirmBtn, 'danger');
      deployConfirmBtn.disabled = false;
      deployConfirmBtn.style.opacity = '1';
      deployConfirmBtn.style.pointerEvents = 'auto';
    }

    updateComposePreview();
  }

  function selectNewInstanceMode() {
    replaceExisting = false;
    if (nameInput) {
      nameInput.value = suggestedContainerName;
      nameInput.style.borderColor = '';
    }
    if (portInput) {
      portInput.value = suggestedPort;
      portInput.style.borderColor = '';
    }

    if (choiceNewBtn) {
      choiceNewBtn.style.border = '2px solid var(--ok2, #33cdb8)';
      choiceNewBtn.style.background = 'rgba(51, 205, 184, 0.18)';
      choiceNewBtn.style.opacity = '1';
      choiceNewBtn.style.boxShadow = '0 0 8px rgba(51,205,184,0.3)';
    }
    if (choiceReplaceBtn) {
      choiceReplaceBtn.style.border = '1px solid rgba(235, 87, 87, 0.4)';
      choiceReplaceBtn.style.background = 'rgba(235, 87, 87, 0.12)';
      choiceReplaceBtn.style.opacity = '0.75';
      choiceReplaceBtn.style.boxShadow = 'none';
    }

    banner.style.background = 'rgba(51, 205, 184, 0.12)';
    banner.style.border = '1px solid var(--ok2, #33cdb8)';
    banner.innerHTML = `<span style="color:var(--ok2, #33cdb8); font-weight:bold;">${ico('✓')} ${t('dk.new_lead', 'New copy:')}</span> ${t('dk.new_instance', 'Setting up {name} on free port {port}, next to the one already there.', { name: bold(suggestedContainerName), port: bold(suggestedPort) })}`;

    if (deployConfirmBtn) {
      setIconLabel(deployConfirmBtn, '🚀', t('ui.deploy_new_instance', 'Install a second copy'));
      setDeployButtonTone(deployConfirmBtn, 'brand');
      deployConfirmBtn.disabled = false;
      deployConfirmBtn.style.opacity = '1';
      deployConfirmBtn.style.pointerEvents = 'auto';
    }

    updateComposePreview();
  }

  if (choiceReplaceBtn) choiceReplaceBtn.onclick = selectReplaceMode;
  if (choiceNewBtn) choiceNewBtn.onclick = selectNewInstanceMode;

  let nameValidationTimer = null;
  async function validateEnteredName() {
    const rawName = nameInput ? nameInput.value.trim() : '';
    if (!rawName) {
      banner.style.background = 'rgba(235, 87, 87, 0.12)';
      banner.style.border = '1px solid var(--err, #eb5757)';
      if (nameInput) nameInput.style.borderColor = 'var(--err, #eb5757)';
      banner.innerHTML = `<span style="color:var(--err, var(--lt-t-eb5757ff, #eb5757)); font-weight:bold;">${ico('✕')} ${t('dk.bad_name_lead', 'Invalid name:')}</span> ${t('dk.bad_name', 'The container needs a name.')}`;
      if (deployConfirmBtn) {
        deployConfirmBtn.disabled = true;
        deployConfirmBtn.style.opacity = '0.5';
        deployConfirmBtn.style.pointerEvents = 'none';
      }
      return;
    }

    try {
      const check = await api.get(`/api/docker/check_container_name?name=${encodeURIComponent(rawName)}`);
      if (check && check.exists) {
        if (replaceExisting && check.name === defaultContainerName) {
          if (nameInput) nameInput.style.borderColor = '';
          banner.style.background = 'rgba(235, 87, 87, 0.12)';
          banner.style.border = '1px solid var(--err, #eb5757)';
          banner.innerHTML = `<span style="color:var(--lt-t-ff8080ff, #ff8080); font-weight:bold;">${ico('⚠️')} ${t('dk.replace_lead', 'Stop & replace:')}</span> ${t('dk.replace_named', 'The container {name} is stopped and replaced.', { name: bold(check.name) })}`;
          if (deployConfirmBtn) {
            deployConfirmBtn.disabled = false;
            deployConfirmBtn.style.opacity = '1';
            deployConfirmBtn.style.pointerEvents = 'auto';
          }
        } else {
          banner.style.background = 'rgba(245, 166, 35, 0.15)';
          banner.style.border = '1px solid var(--warn, #f5a623)';
          if (nameInput) nameInput.style.borderColor = 'var(--warn, #f5a623)';
          banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">${ico('⚠️')} ${t('dk.name_used_lead', 'Name in use:')}</span> ${t('dk.name_used', 'A container named {name} already exists. Choose another name, or choose “Stop & replace”.', { name: bold(check.name) })}`;
          if (deployConfirmBtn) {
            deployConfirmBtn.disabled = true;
            deployConfirmBtn.style.opacity = '0.5';
            deployConfirmBtn.style.pointerEvents = 'none';
          }
        }
      } else {
        if (nameInput) nameInput.style.borderColor = '';
        validateEnteredPort();
      }
    } catch (e) {
      if (nameInput) nameInput.style.borderColor = '';
    }
  }

  let portValidationTimer = null;
  async function validateEnteredPort() {
    const val = parseInt(portInput.value, 10);
    if (!val || val < 1 || val > 65535) {
      banner.style.background = 'rgba(235, 87, 87, 0.12)';
      banner.style.border = '1px solid var(--err, #eb5757)';
      portInput.style.borderColor = 'var(--err, #eb5757)';
      banner.innerHTML = `<span style="color:var(--err, var(--lt-t-eb5757ff, #eb5757)); font-weight:bold;">${ico('✕')} ${t('dk.bad_port_lead', 'Invalid port:')}</span> ${t('dk.bad_port', 'Enter a port from 1 to 65535.')}`;
      if (deployConfirmBtn) {
        deployConfirmBtn.disabled = true;
        deployConfirmBtn.style.opacity = '0.5';
        deployConfirmBtn.style.pointerEvents = 'none';
      }
      return;
    }

    try {
      const check = await api.get(`/api/docker/check_port?port=${val}&proto=tcp`);
      if (check && check.available === false) {
        const cName = nameInput ? nameInput.value.trim() : appId;
        const isOccupiedByTarget = replaceExisting && check.in_use_by && (
          check.in_use_by === `container '${cName}'` ||
          check.in_use_by.includes(cName)
        );

        if (isOccupiedByTarget) {
          banner.style.background = 'rgba(235, 87, 87, 0.12)';
          banner.style.border = '1px solid var(--err, #eb5757)';
          portInput.style.borderColor = '';
          banner.innerHTML = `<span style="color:var(--lt-t-ff8080ff, #ff8080); font-weight:bold;">${ico('⚠️')} ${t('dk.replace_lead', 'Stop & replace:')}</span> ${t('dk.replace_port', 'Port {port} is used by {name}, which is stopped and replaced.', { port: escapeHtml(String(val)), name: bold(cName) })}`;
          if (deployConfirmBtn) {
            deployConfirmBtn.disabled = false;
            deployConfirmBtn.style.opacity = '1';
            deployConfirmBtn.style.pointerEvents = 'auto';
          }
          return;
        }

        banner.style.background = 'rgba(245, 166, 35, 0.15)';
        banner.style.border = '1px solid var(--warn, #f5a623)';
        portInput.style.borderColor = 'var(--warn, #f5a623)';
        banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">${ico('⚠️')} ${t('dk.conflict_lead', 'Port in use:')}</span> ${portBusy(val, check)}`;
        if (deployConfirmBtn) {
          deployConfirmBtn.disabled = true;
          deployConfirmBtn.style.opacity = '0.5';
          deployConfirmBtn.style.pointerEvents = 'none';
        }
      } else {
        banner.style.background = 'rgba(51, 205, 184, 0.12)';
        banner.style.border = '1px solid var(--ok2, #33cdb8)';
        portInput.style.borderColor = '';
        const cName = nameInput ? nameInput.value.trim() : appId;
        banner.innerHTML = `<span style="color:var(--ok2, #33cdb8); font-weight:bold;">${ico('✓')} ${t('dk.ready_lead', 'Ready to install:')}</span> ${t('dk.ready', 'Port {port} is free for the container {name}.', { port: escapeHtml(String(val)), name: bold(cName) })}`;
        if (deployConfirmBtn) {
          deployConfirmBtn.disabled = false;
          deployConfirmBtn.style.opacity = '1';
          deployConfirmBtn.style.pointerEvents = 'auto';
        }
      }
    } catch (err) {
      if (deployConfirmBtn) {
        deployConfirmBtn.disabled = false;
        deployConfirmBtn.style.opacity = '1';
        deployConfirmBtn.style.pointerEvents = 'auto';
      }
    }
  }

  async function updateComposePreview() {
    const p = parseInt(portInput.value, 10) || suggestedPort;
    const s = storageInput.value.trim() || _storageRoot;
    const cName = nameInput ? nameInput.value.trim() : appId;
    try {
      const comp = await api.post(`/api/docker/catalog/${appId}/compose`, {
        host_port: p,
        storage_root: s,
        container_name: cName,
        share_folders: shareFolderPicks(shareMount),
      });
      composePre.textContent = comp.compose_yaml;
    } catch (err) {
      composePre.textContent = `# ${t('ci.compose_failed', 'Could not make the compose file: {error}', { error: err.message })}`;
    }
  }

  if (nameInput) {
    nameInput.oninput = () => {
      updateComposePreview();
      clearTimeout(nameValidationTimer);
      nameValidationTimer = setTimeout(validateEnteredName, 250);
    };
  }

  portInput.oninput = () => {
    updateComposePreview();
    clearTimeout(portValidationTimer);
    portValidationTimer = setTimeout(validateEnteredPort, 250);
  };
  storageInput.oninput = updateComposePreview;
  await renderShareFolders(shareMount, appId, updateComposePreview);
  await updateComposePreview();

  document.getElementById('adm-copy-btn').onclick = () => {
    copyTextToClipboard(composePre.textContent).then((ok) => {
      if (ok) {
        showToast(t('toast.docker_compose_yaml_copied_to_clipboard', 'Docker Compose YAML copied to clipboard!'), 'success');
      } else {
        showToast(t('toast.failed_to_copy_to_clipboard', 'Failed to copy to clipboard'), 'warn');
      }
    });
  };

  document.getElementById('adm-download-btn').onclick = () => {
    const blob = new Blob([composePre.textContent], { type: 'text/yaml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${appId}-compose.yml`;
    a.click();
    URL.revokeObjectURL(url);
    showToast(t('toast.downloaded_compose_yml_2', 'Downloaded {appId}-compose.yml', { appId: appId }), 'info');
  };

  // Deployment execution with live progress bar and streaming console
  const progressFill = document.getElementById('adm-progress-bar-fill');
  const progressPct = document.getElementById('adm-progress-pct-badge');
  const progressStatus = document.getElementById('adm-progress-status-text');
  const progressTitle = document.getElementById('adm-progress-title');
  const progressSpinner = document.getElementById('adm-progress-spinner');
  const deployLogs = document.getElementById('adm-deploy-logs');
  const successBox = document.getElementById('adm-success-box');
  const webuiBtn = document.getElementById('adm-webui-launch-btn');
  const closeProgressBtn = document.getElementById('adm-progress-close-btn');
  const backConfigBtn = document.getElementById('adm-back-to-config-btn');
  const closeBtn = document.getElementById('adm-close-btn');

  function logDeployLine(msg, type = 'info') {
    if (!deployLogs) return;
    const now = new Date().toTimeString().split(' ')[0];
    const color = type === 'error' ? 'var(--crit, #ff6b6b)' : type === 'success' ? 'var(--ok2, #33cdb8)' : '#c9d6d7';
    const line = document.createElement('div');
    line.style.color = color;
    line.textContent = `[${now}] ${msg}`;
    deployLogs.appendChild(line);
    deployLogs.scrollTop = deployLogs.scrollHeight;
  }

  function handleDeployEvent(data) {
    if (!data) return;

    if (data.percent != null && data.step !== 'error') {
      if (progressFill) progressFill.style.width = `${data.percent}%`;
      if (progressPct) progressPct.textContent = `${data.percent}%`;
      if (DockManager && DockManager.windows['app-deploy']) {
        DockManager.windows['app-deploy'].title = `${appId.toUpperCase()} (${data.percent}%)`;
        DockManager.render();
      }
    }
    if (data.message) {
      const said = serverSaid(data, data.message); // the server says how it made the line (SET-14)
      if (progressStatus) progressStatus.textContent = said;
      logDeployLine(said, data.step === 'error' ? 'error' : data.step === 'success' ? 'success' : 'info');
    }

    if (data.step === 'success') {
      if (progressFill) progressFill.style.width = '100%';
      if (progressPct) {
        progressPct.textContent = t('preview.actual_size', '100%');
        progressPct.style.color = 'var(--ok2, #33cdb8)';
      }
      if (progressTitle) progressTitle.textContent = `✓ ${t('dk.installed', '{app} is installed', { app: appId.toUpperCase() })}`;
      if (progressSpinner) {
        progressSpinner.textContent = '✅';
        progressSpinner.style.animation = 'none';
      }

      if (successBox) successBox.style.display = 'flex';
      const webUrl = data.webui_url ? data.webui_url.replace('[HOST]', window.location.hostname) : `http://${window.location.hostname}:${data.port || suggestedPort}`;
      if (webuiBtn) {
        webuiBtn.href = webUrl;
        webuiBtn.textContent = `🌐 ${t('dk.open_webui', 'Open the web page (:{port})', { port: data.port || suggestedPort })} ↗`;
        webuiBtn.style.display = data.has_webui === false ? 'none' : '';
      }
      showDeployCredentials(successBox, data, `${window.location.hostname}:${data.port || suggestedPort}`);
      if (data.setup_unfinished && data.setup_unfinished.length) {
        showToast(t('catalog.setup_unfinished', 'Installed, but some set-up did not finish: {steps}. Open the app to finish it.', { steps: data.setup_unfinished.join(', ') }), 'warn');
      }

      if (closeBtn) {
        closeBtn.disabled = false;
        closeBtn.style.opacity = '1';
        closeBtn.style.pointerEvents = 'auto';
      }
      if (closeProgressBtn) {
        closeProgressBtn.style.display = 'inline-block';
        closeProgressBtn.textContent = t('ui.done', '✓ Done');
      }
      modal._isDeploying = false;

      if (DockManager && DockManager.windows['app-deploy']) {
        DockManager.windows['app-deploy'].title = `✓ ${t('dk.installed', '{app} is installed', { app: appId.toUpperCase() })}`;
        DockManager.render();
      }
      if (modal.classList.contains('window-minimized') || (DockManager && DockManager.windows['app-deploy']?.minimized)) {
        showDockToast(`🚀 ${appId.toUpperCase()} stack deployed and running! Click to open.`, 'app-deploy');
      }

      ZettEventBus.emit('docker:containers:refresh'); // the Apps window reloads its list (SET-25)

      showToast(t('toast.stack_deployed_and_running', '{appId} stack deployed and running!', { appId: appId }), 'success');
    } else if (data.step === 'error') {
      modal._isDeploying = false;
      if (progressSpinner) {
        progressSpinner.textContent = '❌';
        progressSpinner.style.animation = 'none';
      }
      if (progressTitle) progressTitle.textContent = t('ui.deployment_failed', 'Deployment Failed');
      if (progressStatus) progressStatus.style.color = 'var(--crit, #ff6b6b)';
      if (progressPct) progressPct.style.color = 'var(--crit, #ff6b6b)';

      if (closeBtn) {
        closeBtn.disabled = false;
        closeBtn.style.opacity = '1';
        closeBtn.style.pointerEvents = 'auto';
      }
      if (backConfigBtn) backConfigBtn.style.display = 'inline-block';
      if (closeProgressBtn) {
        closeProgressBtn.style.display = 'inline-block';
        closeProgressBtn.textContent = t('diagnostics.close_btn', 'Close');
      }

      if (DockManager && DockManager.windows['app-deploy']) {
        DockManager.windows['app-deploy'].title = `❌ ${t('dk.install_failed', '{app} failed to install', { app: appId.toUpperCase() })}`;
        DockManager.render();
      }
      if (modal.classList.contains('window-minimized') || (DockManager && DockManager.windows['app-deploy']?.minimized)) {
        showDockToast(`❌ ${appId.toUpperCase()} deployment failed! Click to view logs.`, 'app-deploy');
      }

      showToast(t('toast.deployment_failed', 'Deployment failed: {message}', { message: data.message }), 'error');
    }
  }

  deployConfirmBtn.onclick = async () => {
    const p = parseInt(portInput.value, 10) || suggestedPort;
    const s = storageInput.value.trim() || _storageRoot;
    const cName = nameInput ? nameInput.value.trim() : appId;

    // Replacing stops and removes the app there: asked first, naming it (NUX-13)
    if (replaceExisting) {
      const sure = await new Promise((resolve) => {
        showConfirmToast(
          t('catalog.replace_title', 'Replace {name}', { name: cName }),
          t('catalog.replace_msg', '{name} is stopped and replaced by a fresh install. Its settings folder stays, but anything kept only inside the app is lost.', { name: cName }),
          () => resolve(true),
          () => resolve(false),
          { destructive: true, allowHtml: false },
        );
      });
      if (!sure) return;
    }

    if (!replaceExisting) {
      // 1. Verify container name is available
      try {
        const nameCheck = await api.get(`/api/docker/check_container_name?name=${encodeURIComponent(cName)}`);
        if (nameCheck && nameCheck.exists) {
          banner.style.background = 'rgba(245, 166, 35, 0.15)';
          banner.style.border = '1px solid var(--warn, #f5a623)';
          if (nameInput) nameInput.style.borderColor = 'var(--warn, #f5a623)';
          banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">${ico('⚠️')} ${t('dk.name_used_lead', 'Name in use:')}</span> ${t('dk.name_used', 'A container named {name} already exists. Choose another name, or choose “Stop & replace”.', { name: bold(cName) })}`;
          showToast(t('toast.container_already_exists_please_rename_or', 'Container \'{cName}\' already exists. Please rename or select Replace.', { cName: cName }), 'warn');
          return;
        }
      } catch (err) {}

      // 2. Verify port availability before starting deployment
      try {
        const check = await api.get(`/api/docker/check_port?port=${p}&proto=tcp`);
        if (check && check.available === false) {
          banner.style.background = 'rgba(245, 166, 35, 0.15)';
          banner.style.border = '1px solid var(--warn, #f5a623)';
          portInput.style.borderColor = 'var(--warn, #f5a623)';
          banner.innerHTML = `<span style="color:var(--warn, #f5a623); font-weight:bold;">${ico('⚠️')} ${t('dk.conflict_lead', 'Port in use:')}</span> ${portBusy(p, check)}`;
          showToast(t('toast.port_is_already_in_use_please', 'Port {p} is already in use{inUse}. Please change the port.', { p: p, inUse: check.in_use_by ? ` (${check.in_use_by})` : '' }), 'warn');
          return;
        }
      } catch (err) {}
    }

    modal._isDeploying = true;
    modal._activeAppId = appId;

    // Switch views
    viewConfig.style.display = 'none';
    footerConfig.style.display = 'none';
    viewProgress.style.display = 'flex';
    footerProgress.style.display = 'flex';

    // Keep close button interactive while active
    closeBtn.disabled = false;
    closeBtn.style.opacity = '1';
    closeBtn.style.pointerEvents = 'auto';

    // Reset progress UI
    if (progressFill) progressFill.style.width = '0%';
    if (progressPct) {
      progressPct.textContent = '0%';
      progressPct.style.color = 'var(--accent-cyan, #33cdb8)';
    }
    if (progressTitle) progressTitle.textContent = t('catalog.installing_name', 'Installing {name}...', { name: cName });
    if (progressStatus) {
      progressStatus.textContent = t('ui.connecting_to_docker_daemon', 'Connecting to the app service...');
      progressStatus.style.color = 'var(--muted)';
    }
    if (progressSpinner) {
      progressSpinner.textContent = '⚙️';
      progressSpinner.style.animation = 'spin 2s linear infinite';
    }
    if (deployLogs) deployLogs.innerHTML = '';
    if (successBox) successBox.style.display = 'none';
    if (closeProgressBtn) closeProgressBtn.style.display = 'none';
    if (backConfigBtn) backConfigBtn.style.display = 'none';

    logDeployLine(`Initiating deployment request for ${cName} (Port :${p}, Storage: ${s}, Replace: ${replaceExisting})...`);

    try {
      const response = await api.request(`/api/docker/catalog/${appId}/deploy`, {
        method: 'POST',
        body: {
          host_port: p,
          storage_root: s,
          container_name: cName,
          replace_existing: replaceExisting,
          share_folders: shareFolderPicks(shareMount),
          host: window.location.hostname, // apps that set up their own address (COMP-15)
        },
      });

      if (!response.ok) {
        throw new Error(`Deployment request failed: HTTP ${response.status}`);
      }

      if (!response.body || !response.body.getReader) {
        const text = await response.text();
        const lines = text.split('\n').filter(Boolean);
        for (const line of lines) {
          try {
            const data = JSON.parse(line);
            handleDeployEvent(data);
          } catch (e) {}
        }
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const eventData = JSON.parse(line);
            handleDeployEvent(eventData);
          } catch (err) {
            console.warn('NDJSON parsing error:', err, line);
          }
        }
      }

      if (buffer.trim()) {
        try {
          const eventData = JSON.parse(buffer);
          handleDeployEvent(eventData);
        } catch (e) {}
      }
    } catch (err) {
      modal._isDeploying = false;
      handleDeployEvent({
        step: 'error',
        percent: 0,
        message: err.message || t('dk.install_lost', 'The connection to the install was lost'),
        error: err.message,
        done: true,
      });
    }
  };

  if (backConfigBtn) {
    backConfigBtn.onclick = () => {
      viewProgress.style.display = 'none';
      footerProgress.style.display = 'none';
      viewConfig.style.display = 'flex';
      footerConfig.style.display = 'flex';
    };
  }

  if (closeProgressBtn) {
    closeProgressBtn.onclick = () => {
      modal._isDeploying = false;
      if (modal._close) modal._close();
    };
  }
}

/** @type {string[]} the apps that are not running, as the clean-up dialog last read them */
let _stoppedApps = [];

/**
 * Says which apps "Remove stopped apps" would remove; with none, the option cannot be ticked.
 * @param {string[]} names
 */
export function showStoppedApps(names) {
  _stoppedApps = names;
  const box = /** @type {HTMLInputElement | null} */ (document.getElementById('dpm-opt-containers'));
  const title = document.getElementById('dpm-opt-containers-title');
  const desc = document.getElementById('dpm-opt-containers-desc');
  if (title) title.textContent = t('dk.p_containers_n', '{count, plural, one {Remove # stopped app} other {Remove # stopped apps}}', { count: names.length });
  if (desc) {
    desc.textContent = names.length
      ? t('dk.p_containers_names', 'These are not running and would be removed, with their set-up: {names}. Their folders stay. Leave this off unless you know every one of them.', { names: names.join(', ') })
      : t('dk.p_containers_none', 'Every app is running: nothing to remove.');
  }
  if (box) {
    box.disabled = names.length === 0;
    if (!names.length) box.checked = false;
  }
}

/**
 * The second question before stopped apps are removed.
 * @param {string[]} names
 * @returns {Promise<boolean>}
 */
export function askRemoveStopped(names) {
  return new Promise((resolve) => {
    showDangerConfirm(
      t('dk.remove_stopped_title', '{count, plural, one {Remove # stopped app?} other {Remove # stopped apps?}}', { count: names.length }),
      t('dk.remove_stopped_msg', 'These apps and their set-up are removed for good: {names}. Their folders stay where they are. An app you stopped on purpose is gone as well.', { names: names.join(', ') }),
      () => resolve(true), () => resolve(false),
      { okText: t('dk.remove_stopped_ok', 'Remove them') },
    );
  });
}

export async function openDockerPruneModal() {
  let modal = document.getElementById('docker-prune-modal-overlay');
  if (!modal) {
    const html = `
      <div id="docker-prune-modal-overlay" class="smart-modal-backdrop" style="display:none; z-index:10020;">
        <div id="docker-prune-modal-window" class="smart-modal-window dkd-size-2" style="display: flex;">
          <div class="smart-modal-header dkd-row-7">
            <div class="dkd-row">
              <span class="dkd-fs18">🧹</span>
              <span class="dkd-fs13-bold-strong">${t('dk.prune_title', 'Docker cleanup')}</span>
            </div>
            <button class="win-btn close-btn" id="dpm-close-btn" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
          </div>
          <div class="dkd-col-2">
            <div class="dkd-xs-soft-3">
              ${t('dk.prune_desc', 'Free space by removing Docker data nothing uses. Running containers are safe.')}
            </div>

            <!-- Live Disk Usage Breakdown -->
            <div class="dkd-x-4" id="dpm-df-summary" style="display: grid;">
              <div class="dkd-box-center">
                <div class="dkd-xs-bold-muted-2">${t('dk.images', 'Images')}</div>
                <div class="dkd-xs-bold-strong" id="dpm-df-images">${t('common.loading', 'Loading…')}</div>
              </div>
              <div class="dkd-box-center">
                <div class="dkd-xs-bold-muted-2">${t('dk.containers', 'Containers')}</div>
                <div class="dkd-xs-bold-strong" id="dpm-df-containers">${t('common.loading', 'Loading…')}</div>
              </div>
              <div class="dkd-box-center">
                <div class="dkd-xs-bold-muted-2">${t('dk.volumes', 'Volumes')}</div>
                <div class="dkd-xs-bold-strong" id="dpm-df-volumes">${t('common.loading', 'Loading…')}</div>
              </div>
              <div style="background:var(--lt-b-33cdb80f, rgba(51,205,184,0.06)); border:1px solid var(--lt-r-33cdb833, rgba(51,205,184,0.2)); padding:8px 10px; border-radius:6px; text-align:center;">
                <div style="font-size:var(--kb-fs-xs); color:var(--lt-ink-brand, var(--accent-cyan, #33cdb8)); text-transform:uppercase; font-weight:700;">${t('dk.reclaimable', 'Can be freed')}</div>
                <div id="dpm-df-reclaimable" style="font-size:var(--kb-fs-xs); font-weight:800; color:var(--ok2, #33cdb8); margin-top:2px;">--</div>
              </div>
            </div>

            <!-- Prune Options -->
            <div class="dpm-opts dkd-col-box">
              <label class="dkd-row-xs">
                <input class="dkd-x-5" type="checkbox" id="dpm-opt-containers">
                <div>
                  <strong id="dpm-opt-containers-title">${t('dk.p_containers', 'Remove stopped apps')}</strong>
                  <div class="dkd-xs-muted-2" id="dpm-opt-containers-desc">${t('dk.p_containers_d', 'Removes apps that are not running, with their set-up. Their folders stay. Leave this off unless you know every one of them.')}</div>
                </div>
              </label>
              <label class="dkd-row-xs">
                <input class="dkd-x-5" type="checkbox" id="dpm-opt-images" checked>
                <div>
                  <strong>${t('dk.p_dangling', 'Remove leftovers from old updates')}</strong>
                  <div class="dkd-xs-muted-2">${t('dk.p_dangling_d', 'Removes untagged “none” build layers and leftover images.')}</div>
                </div>
              </label>
              <label class="dkd-row-xs">
                <input class="dkd-x-5" type="checkbox" id="dpm-opt-all-images">
                <div>
                  <strong>${t('dk.p_unused', 'Remove all unused images')}</strong>
                  <div class="dkd-xs-muted-2">${t('dk.p_unused_d', 'Removes images no container uses, running or stopped. Images of stopped containers (such as update rollbacks) are kept.')}</div>
                </div>
              </label>
              <label class="dkd-row-xs">
                <input class="dkd-x-5" type="checkbox" id="dpm-opt-volumes">
                <div>
                  <strong>${t('dk.p_volumes', 'Remove unused local volumes')}</strong>
                  <div style="font-size:var(--kb-fs-xs); color:var(--warn, #f5a623);">${t('dk.p_volumes_d', 'Careful: removes anonymous local volumes no container mounts.')}</div>
                </div>
              </label>
              <label class="dkd-row-xs">
                <input class="dkd-x-5" type="checkbox" id="dpm-opt-buildcache" checked>
                <div>
                  <strong>${t('dk.p_cache', 'Remove build cache & unused networks')}</strong>
                  <div class="dkd-xs-muted-2">${t('dk.p_cache_d', 'Frees Docker’s temporary build cache and bridge networks nothing is connected to.')}</div>
                </div>
              </label>
            </div>

            <!-- Progress while the cleanup runs (it continues if this dialog is closed) -->
            <div id="dpm-progress" class="kb-card kb-box" hidden>
              <div class="kb-row kb-row--between">
                <span id="dpm-progress-msg" class="kb-muted"></span>
                <strong id="dpm-progress-pct" class="dpm-progress-pct">0%</strong>
              </div>
              <div class="dpm-bar" id="dpm-bar" role="progressbar" aria-label="${t('ui.cleanup_progress', 'Cleanup progress')}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div class="dpm-bar-fill" id="dpm-bar-fill"></div></div>
              <ul class="kb-list" id="dpm-steps"></ul>
              <div class="kb-muted" id="dpm-freed"></div>
            </div>
          </div>
          <div class="dkd-row-box">
            <button class="btn-pill-toggle" id="dpm-cancel-btn">${t('common.cancel', 'Cancel')}</button>
            <button class="btn-pill-toggle is-primary" id="dpm-confirm-btn">
              ${ico('🧹')} ${t('dk.run_prune', 'Clean up and free space')}
            </button>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
    modal = document.getElementById('docker-prune-modal-overlay');

    const closeModal = () => {
      modal.classList.remove('open');
      modal.style.display = 'none';
    };
    document.getElementById('dpm-close-btn').onclick = (e) => { e.preventDefault(); closeModal(); };
    document.getElementById('dpm-cancel-btn').onclick = (e) => { e.preventDefault(); closeModal(); };
    modal.onclick = (e) => { if (e.target === modal) closeModal(); };
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('open')) closeModal();
    });

    const optImages = document.getElementById('dpm-opt-images');
    const optAllImages = document.getElementById('dpm-opt-all-images');
    const syncImageOptions = () => {
      if (optAllImages && optImages) {
        if (optAllImages.checked) {
          optImages.checked = true;
          optImages.disabled = true;
          optImages.parentElement.style.opacity = '0.5';
        } else {
          optImages.disabled = false;
          optImages.parentElement.style.opacity = '1';
        }
      }
    };
    if (optAllImages) optAllImages.onchange = syncImageOptions;
  }

  modal.classList.add('open');
  modal.style.display = 'flex';

  // Fetch live system df metrics
  try {
    const df = await api.get('/api/docker/system/df');
    const imgEl = document.getElementById('dpm-df-images');
    const cntEl = document.getElementById('dpm-df-containers');
    const volEl = document.getElementById('dpm-df-volumes');
    const recEl = document.getElementById('dpm-df-reclaimable');

    if (imgEl && df.images) imgEl.textContent = t('dkd.df_images', '{total} ({unused} unused)', { total: df.images.total_count, unused: df.images.unused_count });
    if (cntEl && df.containers) cntEl.textContent = t('dkd.df_containers', '{total} ({stopped} stopped)', { total: df.containers.total_count, stopped: df.containers.stopped_count });
    showStoppedApps((df.containers && df.containers.stopped_names) || []);
    if (volEl && df.volumes) volEl.textContent = t('dkd.df_images', '{total} ({unused} unused)', { total: df.volumes.total_count, unused: df.volumes.unused_count });
    if (recEl) recEl.textContent = df.total_reclaimable_human || '0 B';
  } catch (err) {
    // the tiles stayed on "Loading…" for ever next to an empty bar (SET-14)
    console.warn('Failed to load system df:', err);
    for (const id of ['dpm-df-images', 'dpm-df-containers', 'dpm-df-volumes', 'dpm-df-reclaimable']) {
      const el = document.getElementById(id);
      if (el) el.textContent = t('dkd.df_unknown', 'Not known');
    }
  }

  const confirmBtn = document.getElementById('dpm-confirm-btn');
  setPruneIdle();

  confirmBtn.onclick = async () => {
    if (confirmBtn.dataset.mode === 'done') {
      modal.classList.remove('open');
      modal.style.display = 'none';
      setPruneIdle();
      return;
    }
    const allImages = document.getElementById('dpm-opt-all-images').checked;
    const pruneBuildCache = document.getElementById('dpm-opt-buildcache').checked;
    const removeStopped = document.getElementById('dpm-opt-containers').checked && _stoppedApps.length > 0;
    // removing apps is asked once more, by name: the one button used to start it at once
    if (removeStopped && !(await askRemoveStopped(_stoppedApps))) return;
    confirmBtn.disabled = true;
    try {
      const res = await api.post('/api/docker/system/prune/jobs', {
        prune_containers: removeStopped,
        prune_images: document.getElementById('dpm-opt-images').checked || allImages,
        all_images: allImages,
        prune_volumes: document.getElementById('dpm-opt-volumes').checked,
        prune_networks: pruneBuildCache,
        prune_build_cache: pruneBuildCache,
      });
      followPruneJob(res.job);
    } catch (err) {
      showToast(t('toast.prune_failed', 'Prune failed: {error}', { error: err.message }), 'error');
      setPruneIdle();
    }
  };

  // A cleanup started earlier (maybe from another tab) is still running: show it.
  try {
    const cur = await api.get('/api/docker/system/prune/jobs/current');
    if (cur && cur.job && cur.job.state === 'running') followPruneJob(cur.job);
  } catch (err) {
    console.warn('Could not check for a running cleanup:', err);
  }
}

const PRUNE_STEP_LABELS = () => ({
  containers: t('prune.step_containers', 'Stopped containers'),
  images: t('prune.step_images', 'Unused images'),
  volumes: t('prune.step_volumes', 'Unused volumes'),
  networks: t('prune.step_networks', 'Unused networks'),
  build_cache: t('prune.step_build_cache', 'Build cache'),
});
const PRUNE_STEP_ICONS = { pending: '○', running: '◐', done: '✓', skipped: '–', error: '!' };
let _prunePollTimer = null;

function setPruneIdle() {
  const btn = document.getElementById('dpm-confirm-btn');
  const cancel = document.getElementById('dpm-cancel-btn');
  const opts = document.getElementById('dpm-opt-containers')?.closest('.dpm-opts');
  if (btn) {
    btn.disabled = false;
    btn.dataset.mode = 'start';
    btn.textContent = `🧹 ${t('dk.run_prune', 'Clean up and free space')}`;
  }
  if (cancel) {
    cancel.hidden = false;
    cancel.textContent = t('common.cancel', 'Cancel');
    cancel.onclick = (e) => {
      e.preventDefault();
      const m = document.getElementById('docker-prune-modal-overlay');
      if (m) { m.classList.remove('open'); m.style.display = 'none'; }
    };
  }
  if (opts) opts.inert = false;
  const prog = document.getElementById('dpm-progress');
  if (prog) prog.hidden = true;
}

export function renderPruneJob(job) {
  const prog = document.getElementById('dpm-progress');
  if (!prog || !job) return;
  prog.hidden = false;
  const labels = PRUNE_STEP_LABELS();
  const pct = Math.max(0, Math.min(100, job.percent || 0));
  const fill = document.getElementById('dpm-bar-fill');
  if (fill) fill.style.width = `${pct}%`;
  document.getElementById('dpm-bar')?.setAttribute('aria-valuenow', String(pct));
  const pctEl = document.getElementById('dpm-progress-pct');
  if (pctEl) pctEl.textContent = `${pct}%`;
  const msgEl = document.getElementById('dpm-progress-msg');
  if (msgEl) {
    let msg = job.step ? `${labels[job.step] || job.step}…` : '';
    if (job.step === 'images' && job.images_phase === 'before') msg = t('prune.measuring_before', 'Measuring what the images use…');
    else if (job.step === 'images' && job.images_phase === 'sweep') msg = t('prune.sweeping', 'Clearing the layers those images used…');
    else if (job.step === 'images' && job.images_phase === 'after') msg = t('prune.measuring_after', 'Measuring the space freed…');
    else if (job.step === 'images' && job.images_total) {
      msg = t('prune.images_progress', 'Removing image {done} of {total}', { done: Math.min(job.images_done + 1, job.images_total), total: job.images_total });
    }
    if (job.state !== 'running') msg = '';
    msgEl.textContent = msg;
  }
  const list = document.getElementById('dpm-steps');
  if (list) {
    list.replaceChildren(...(job.steps || []).map((s) => {
      const li = document.createElement('li');
      li.className = `dpm-step is-${s.state}`;
      const icon = Object.assign(document.createElement('span'), { className: 'dpm-step-icon', textContent: PRUNE_STEP_ICONS[s.state] || '○' });
      icon.setAttribute('aria-hidden', 'true');
      const name = Object.assign(document.createElement('span'), { textContent: labels[s.key] || s.key });
      let detail = s.detail || '';
      if (s.key === 'images' && s.state === 'running' && job.images_total) detail = `${job.images_done} / ${job.images_total}`;
      if (s.freed_bytes > 0) detail = `${detail}${detail ? ' · ' : ''}${formatSize(s.freed_bytes)}`;
      const det = Object.assign(document.createElement('span'), { className: 'kb-push-end kb-muted', textContent: detail });
      li.append(icon, name, det);
      return li;
    }));
  }
  const freed = document.getElementById('dpm-freed');
  if (freed) freed.textContent = t('prune.freed', '{freed} freed so far', { freed: job.freed_human || '0 B' });
}

function followPruneJob(job) {
  const btn = document.getElementById('dpm-confirm-btn');
  const cancel = document.getElementById('dpm-cancel-btn');
  const opts = document.getElementById('dpm-opt-containers')?.closest('.dpm-opts');
  if (opts) opts.inert = true;
  if (cancel) {
    cancel.hidden = false;
    cancel.textContent = t('prune.stop', 'Stop');
    cancel.onclick = async (e) => {
      e.preventDefault();
      cancel.disabled = true;
      try { await api.post(`/api/docker/system/prune/jobs/${job.id}/cancel`, {}); } catch (err) { console.warn('Stop failed:', err); }
      cancel.disabled = false;
    };
  }
  const tick = (j) => {
    renderPruneJob(j);
    if (btn) {
      btn.disabled = true;
      btn.textContent = t('prune.running_pct', 'Cleaning up… {pct}%', { pct: j.percent || 0 });
    }
    if (j.state !== 'running') finishPruneJob(j);
  };
  tick(job);
  if (_prunePollTimer) clearInterval(_prunePollTimer);
  if (job.state !== 'running') return;
  _prunePollTimer = setInterval(async () => {
    try {
      const res = await api.get(`/api/docker/system/prune/jobs/${job.id}`);
      tick(res.job);
    } catch (err) {
      console.warn('Cleanup progress unavailable:', err);
    }
  }, 900);
}

async function finishPruneJob(job) {
  if (_prunePollTimer) { clearInterval(_prunePollTimer); _prunePollTimer = null; }
  renderPruneJob(job);
  const freed = job.freed_human || '0 B';
  if (job.state === 'cancelled') {
    showToast(t('prune.stopped', 'Cleanup stopped: {freed} freed so far.', { freed }), 'info');
  } else if (job.errors && job.errors.length) {
    showToast(t('prune.done_errors', 'Cleanup finished with errors: {freed} freed. {errors}', { freed, errors: job.errors.join('; ') }), 'warning');
  } else {
    showToast(t('prune.done', 'Cleanup finished: {freed} freed.', { freed }), 'success');
  }
  const btn = document.getElementById('dpm-confirm-btn');
  const cancel = document.getElementById('dpm-cancel-btn');
  if (btn) {
    btn.disabled = false;
    btn.dataset.mode = 'done';
    btn.textContent = t('prune.close', 'Done');
  }
  if (cancel) cancel.hidden = true;
  ZettEventBus.emit('docker:containers:refresh'); // the Apps window reloads its list (SET-25)
}
