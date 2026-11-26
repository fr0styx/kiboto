import { syncWidgetSettingsUI } from './widgets.js';
import { isNvmeDrive } from './temp-rule.js';
import { refreshAndSay } from './refresh-say.js';
import { isShuttingDown } from './vm/power.js';
import {
  loadAccountPane,
  loadBackupExtras,
  loadSecurityPane,
  loadNotificationsPane,
  loadConnectionsPane,
} from './management/admin-panes.js';
import { kibPaneFor, loadKibExtras, mayManageKib } from './management/kib-access.js';

const KIB_WINDOW_PANES = new Set(['mgmt-pane-ai-chat', 'mgmt-pane-ai-rag', 'mgmt-pane-ai-visual']);
import { syncDesktopThemeUI, openDrawer, restoreHardwareTabsToManagement } from './settings.js';
import { ZettEventBus } from '../event-bus.js';
import { fitMiniPreviewScale, syncMiniPreviewTelemetry } from './mini-preview.js';
import {
  fetchAndRenderChassisTwin,
  fetchAndRenderStorageTopology,
  fetchAndRenderNetworkShares,
  fetchAndRenderRemoteStorage,
  openNewCloudRemoteModal,
  openCreateStoragePoolModal,
  getThermalLevel,
} from './chassis-visualizer.js';
import { bringToFront, DockManager, makeDraggable, saveWindowBounds, saveOpenWindowsState } from './dock.js';
import { state } from '../state.js';
import { api } from '../api.js';
import { showToast } from '../toast.js';
import { trapFocus, escapeHtml, copyTextToClipboard } from '../utils.js';
import { t, getLanguage } from '../i18n.js';
import '../styles/management-lazy.css'; // Mission Control's own sheet loads with this code (ARC-12)
import { wireTablists, markCurrent } from './tab-a11y.js';
import { highlightEntry, mayNotOpen } from './management/sidebar-current.js';
import { openFilePreviewModal } from './file-preview-modal.js';
import {
  fetchAndRenderUpsTelemetry,
  initUpsDrawerControls,
  loadUpsConfigToDrawer,
  renderUpsTelemetry,
} from './management/ups.js';
import {
  fetchAndRenderCopyHistory,
  fetchAndRenderNetworkTopology,
  fetchAndRenderReplication,
  fetchAndRenderTailscaleDetails,
  initNetworkControls,
  loadNetworkPage,
} from './management/network.js';
import { fetchAndRenderDisksInventory } from './management/disks.js';
import { closeHttpsGuideModal, handleSecurityAdvisorClick } from './management/security.js';
import {
  applySystemUpdate,
  closeDiagnosticsPreviewModal,
  copySupportMarkdown,
  downloadDiagnosticsBundle,
  fetchAndRenderSystemAbout,
  previewDiagnosticsSummary,
  revertSystemUpdate,
  setUpdateChannel,
  syncBackupJobForm,
} from './management/system.js';
import {
  openChannelConfigModal,
  saveCurrentChannelModal,
  saveNotificationsConfig,
  testAllNotificationChannels,
  testSingleChannel,
} from './management/notifications.js';
import {
  fetchAndRenderAppBackups,
  fetchAndRenderBackupJobs,
  fetchAndRenderSystemSnapshots,
  loadBackupPane,
} from './management/backup.js';
import { installAdvancedSwitch, installSidebarGroups, renderStatusSummary } from './management/overview.js';
import { installHealthSignal } from './management/health-signal.js';
import {
  _aiSelectedColor,
  _aiSelectedScene,
  _getActiveAiSearchQuery,
  _renderAiRagInitialEmptyState,
  fetchAndRenderAiStatus,
  initAiKnowledgeEngine,
  runAiVisualSearch,
  setAiVisualFiltersDrawerOpen,
} from './management/ai.js';
import { formatFixed } from '../format.js';
import { watchSideScrollIn } from '../side-scroll.js';
import { slowNoteHtml } from './vm/slow-mode.js';
import { FIXED_PCT, askFixedSpeed, modeName } from './fan-modes.js';
import { renderCoolingStatus } from './hw-status.js';

export * from './management/docker.js';
export * from './management/ups.js';
export * from './management/network.js';
export * from './management/disks.js';
export * from './management/security.js';
export * from './management/system.js';
export * from './management/notifications.js';
export * from './management/backup.js';
export * from './management/ai.js';

if (typeof window !== 'undefined') {
  window.openFilePreviewModal = openFilePreviewModal;
}

let _activeProfile = 'balanced';
let _unbindMgmtTrap = null;

// The deploy button: a soft tint of the accent with a thin border, like the dialog's other controls.

/** The window's title icon: the page's own from the sidebar (Kib's face for Kib), Settings' on the
 * overview. It showed Settings' grid on every page. */
export function titleIconOf(targetId, doc = document) {
  const use = doc.querySelector('#management-window-header .mgmt-title-ic use');
  if (!use) return;
  const item = targetId ? doc.querySelector(`.mgmt-sidebar-item[data-mgmt-target="${targetId}"] use`) : null;
  use.setAttribute('href', item?.getAttribute('href') || '#i-management');
}

export function setDeployButtonTone(btn, tone) {
  const color = tone === 'danger' ? 'var(--err, #eb5757)' : 'var(--brand, #33cdb8)';
  btn.style.background = `color-mix(in srgb, ${color} 22%, transparent)`;
  btn.style.border = `1px solid color-mix(in srgb, ${color} 55%, transparent)`;
  btn.style.color = 'var(--text, #e6eaea)';
}

export const SUBPANE_MAP = {
  // --- Pillar 1: Dashboard & Telemetry ---
  'dashboard': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
  'activity': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-events' }, // History first (SET-27)
  'telemetry': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
  'mgmt-sec-activity': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-events' },
  'mgmt-sec-metrics': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },
  'mgmt-pane-metrics': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-metrics' },

  // --- Pillar 2: Storage & Disks ---
  'storage': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-chassis-twin' },
  'mgmt-sec-storage': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-chassis-twin' },
  'mgmt-pane-chassis-twin': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-chassis-twin' },
  'mgmt-pane-chassis': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-topo' },
  'mgmt-sec-pools': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-topo' },
  'mgmt-pane-pools': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-topo' },
  'storage-pools': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-topo' },
  'mgmt-pane-storage-topo': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-topo' },
  'mgmt-pane-storage-shares': { section: 'mgmt-sec-shares', pane: 'mgmt-pane-storage-shares' },
  'mgmt-sec-shares': { section: 'mgmt-sec-shares', pane: 'mgmt-pane-storage-shares' }, // its own section (SET-22)
  'mgmt-pane-storage-remotes': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-remotes' },
  'mgmt-pane-storage-disks': { section: 'mgmt-sec-storage', pane: 'mgmt-pane-storage-disks' },
  'mgmt-sec-copy': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-copy' },
  'mgmt-pane-copy': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-copy' },
  'mgmt-pane-storage-ingest': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-copy' },
  'mgmt-sec-ingest': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-copy' },
  'mgmt-pane-storage-replication': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-backups' }, // moved to Backup (SET-22 Storage 3)

  // --- Pillar 3: Containers & Apps ---
  'containers': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'docker': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'apps': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-sec-docker': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-pane-docker': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-sec-catalog': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-pane-docker-compose': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },
  'mgmt-pane-docker-catalog': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker-catalog' },
  'catalog': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker-catalog' },
  'mgmt-pane-docker-prune': { section: 'mgmt-sec-docker', pane: 'mgmt-pane-docker' },

  // --- Pillar 4: Virtual Machines ---
  'vms': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-list' },
  'vm': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-list' },
  'vm-manager': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-list' },
  'mgmt-sec-vms': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-list' },
  'mgmt-pane-vms-list': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-list' },
  'mgmt-pane-vms-create': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-create' },
  'mgmt-pane-vms-kvm': { section: 'mgmt-sec-vms', pane: 'mgmt-pane-vms-kvm' },

  // --- Pillar 5: Network & Sharing ---
  'network': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network' },
  'mgmt-sec-network': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network' },
  'mgmt-pane-network': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network' },
  'mgmt-pane-network-physical': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network' },
  'mgmt-pane-network-wireguard': { section: 'mgmt-sec-away', pane: 'mgmt-pane-network-wireguard' },
  'mgmt-sec-away': { section: 'mgmt-sec-away', pane: 'mgmt-pane-network-wireguard' }, // Away from home, its own page (SET-24)
  'mgmt-pane-network-services': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network' }, // sections of one page now (SET-24)
  'mgmt-pane-network-ports': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network' },
  'ports': { section: 'mgmt-sec-network', pane: 'mgmt-pane-network' },

  // --- Pillar 6: Hardware & Profiles ---
  'hardware': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  'mgmt-sec-hardware': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  'mgmt-pane-hardware': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  'mgmt-sec-services': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' }, // Backward compat
  'mgmt-sec-unraid': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  'mgmt-pane-unraid': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-unraid' },
  'mgmt-pane-hardware-fans': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-hardware-fans' },
  'mgmt-pane-hardware-led': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-hardware-led' },
  'mgmt-pane-hardware-lcd': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-hardware-lcd' },
  'mgmt-pane-hardware-copy': { section: 'mgmt-sec-hardware', pane: 'mgmt-pane-hardware-copy' },
  'mgmt-pane-hardware-ups': { section: 'mgmt-sec-ups', pane: null },

  // --- Pillar 7: Power & Battery (Dedicated 1st-Class Section) ---
  'power': { section: 'mgmt-sec-ups', pane: null },
  'mgmt-sec-ups': { section: 'mgmt-sec-ups', pane: null },
  'ups': { section: 'mgmt-sec-ups', pane: null },
  'mgmt-pane-ups': { section: 'mgmt-sec-ups', pane: null },

  // --- Pillar 7: System & Identity ---
  'system': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
  'mgmt-sec-system': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-backups' },
  'mgmt-sec-system-group': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
  'mgmt-pane-system': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-backups' },
  'mgmt-sec-security': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
  'mgmt-pane-security': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-security' },
  'mgmt-sec-users': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-users' },
  'mgmt-pane-users': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-users' },
  'mgmt-pane-account': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-account' }, // My account (SET-19)
  'mgmt-sec-backups': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-backups' },
  'mgmt-pane-backups': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-backups' },
  'mgmt-sec-notifications': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-notifications' },
  'mgmt-pane-notifications': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-notifications' },
  'mgmt-sec-events': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-events' },
  'mgmt-pane-events': { section: 'mgmt-sec-activity', pane: 'mgmt-pane-events' },
  'mgmt-sec-about': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-about' },
  'mgmt-pane-about': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-about' },
  'mgmt-pane-connections': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-connections' }, // SET-23, decision 8

  // --- Appearance (Preserving Wallpaper section compatibility) ---
  'appearance': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-wallpaper' },
  'mgmt-sec-wallpaper': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-wallpaper' },
  'mgmt-pane-wallpaper': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-wallpaper' },
  'mgmt-pane-widgets': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-widgets' },
  'mgmt-pane-theme': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-theme' },
  'mgmt-sec-theme': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-theme' },
  'mgmt-pane-glass': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-glass' },
  'mgmt-sec-glass': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-glass' },
  'mgmt-pane-dock': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-dock' },
  'mgmt-sec-dock': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-dock' },
  'mgmt-pane-screensaver': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-screensaver' },
  'mgmt-sec-screensaver': { section: 'mgmt-sec-wallpaper', pane: 'mgmt-pane-screensaver' },
  'mgmt-sec-calendar': { section: 'mgmt-sec-calendar', pane: 'mgmt-pane-calendar' },
  'mgmt-pane-calendar': { section: 'mgmt-sec-calendar', pane: 'mgmt-pane-calendar' },
  'calendar': { section: 'mgmt-sec-calendar', pane: 'mgmt-pane-calendar' },
  'mgmt-sec-language': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-language' },
  'mgmt-pane-language': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-language' },
  'timezone': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-language' },
  'clock': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-language' },
  'time': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-language' },
  'language': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-language' },
  'region': { section: 'mgmt-sec-system-group', pane: 'mgmt-pane-language' },

  // --- Pillar 8: AI Knowledge & Visual Search (Kib) ---
  // Settings → Kib is the settings; Ask and Search open the Kib window (AI decision 1)
  'ai': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-index' },
  'chatbot': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' },
  'chat': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' },
  'rag': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-rag' },
  'zettai': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' },
  'ai-chat': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' },
  'mgmt-sec-ai': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-index' },
  'mgmt-sec-ai-rag': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-rag' },
  'mgmt-pane-ai-rag': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-rag' },
  'mgmt-pane-ai-chat': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-chat' },
  'mgmt-pane-ai-visual': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-visual' },
  'mgmt-pane-ai-index': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-index' },
};

/** "Intel Core Ultra 5 125H · 18 threads" (About → Technical details). */
export function processorWords(cpu) {
  const c = cpu || {};
  const name = c.model
    ? c.model
        .replace(/\(R\)|\(TM\)/g, '')
        .replace(/\s+/g, ' ')
        .trim()
    : t('hw.cpu_unknown', 'Not reported');
  return c.cores
    ? `${name} · ${t('hw.threads', '{n, plural, one {# thread} other {# threads}}', { n: c.cores })}`
    : name;
}

const POWER_MODES = {
  performance: ['hw.gov_performance', 'Full speed'],
  powersave: ['hw.gov_powersave', 'Power saving'],
  schedutil: ['hw.gov_adaptive', 'Adjusts to the load'],
  ondemand: ['hw.gov_adaptive', 'Adjusts to the load'],
  conservative: ['hw.gov_adaptive', 'Adjusts to the load'],
};
/** The processor's scaling governor in words ("powersave" → "Power saving"); an unknown one as it is. */
export function powerModeWord(governor) {
  const m = POWER_MODES[String(governor || '').toLowerCase()];
  return m ? t(m[0], m[1]) : String(governor || '');
}

/** One line for the graphics chip: its name and whether video is done in hardware. */
export function graphicsWords(gpu) {
  const g = gpu || {};
  const name = g.model || t('hw.no_gpu', 'No graphics chip found');
  const codecs = Array.isArray(g.codecs) ? g.codecs.filter(Boolean) : [];
  if (g.ready && codecs.length)
    return `${name} · ${t('hw.gpu_video_hw', 'video in hardware: {codecs}', { codecs: codecs.join(', ') })}`;
  return g.model ? `${name} · ${t('hw.gpu_video_sw', 'video in software')}` : name;
}

// "Load → Activity" and the other buttons that send a fact's old place to its new page (Hardware 3)
document.addEventListener('click', (e) => {
  const target = e.target instanceof Element ? e.target : null;
  const b = /** @type {HTMLElement|null} */ (target && target.closest('[data-goto-section]'));
  const open = /** @type {any} */ (window).openManagementWindow;
  if (!b || typeof open !== 'function') return;
  open(b.dataset.gotoSection, b.dataset.gotoPane || undefined);
});

export function updateManagementTelemetry(stats) {
  if (!stats) return;
  const overlay = document.getElementById('management-modal-overlay');
  const shut =
    overlay &&
    (!overlay.classList.contains('open') ||
      overlay.classList.contains('window-minimized') ||
      overlay.style.display === 'none');
  // the Hardware panel holds the Hardware page's sections: they follow the readings while it is open
  if (shut && !document.body.classList.contains('hwd-is-open')) return;
  const unraid = stats.unraid;
  // Hardware 3: the facts live on About, Storage and Kib; rows for the other kind of host stay hidden
  const hostKind = unraid && unraid.available ? 'unraid' : 'generic';
  document.querySelectorAll('[data-host]').forEach((node) => {
    const el = /** @type {HTMLElement} */ (node);
    el.style.display = el.dataset.host === hostKind ? '' : 'none';
  });
  const setText = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
    return el;
  };

  if (hostKind === 'unraid') {
    const stateEl = setText('mgmt-unraid-state', unraid.state || '—');
    if (stateEl) stateEl.style.color = unraid.color?.startsWith('green') ? 'var(--ok2)' : 'var(--warn)';
    setText('mgmt-unraid-version', `Unraid ${unraid.version || ''}`.trim());
    const d = unraid.disks || {};
    setText(
      'mgmt-unraid-disks',
      t('mgx.disks', '{count, plural, one {# Disk} other {# Disks}} ({disabled} disabled, {invalid} invalid)', {
        count: d.total || 0,
        disabled: d.disabled || 0,
        invalid: d.invalid || 0,
      })
    );
    const parityEl = document.getElementById('mgmt-unraid-parity');
    if (parityEl) {
      const p = unraid.parity_check || {};
      if (p.active) {
        parityEl.textContent = t(
          'mgx.parity_active',
          'Active ({action} {pct}%) • {count, plural, one {# Error} other {# Errors}}',
          { action: p.action || t('mgx.sync', 'Sync'), pct: p.progress_pct || 0, count: p.errors || 0 }
        );
        parityEl.style.color = 'var(--accent-cyan,#33cdb8)';
      } else {
        parityEl.textContent = t(
          'mgx.parity_idle',
          'Completed / Idle • {count, plural, one {# Error} other {# Errors}}',
          { count: p.errors || 0 }
        );
        parityEl.style.color = 'var(--ok2)';
      }
    }
    const moverEl = document.getElementById('mgmt-unraid-mover');
    if (moverEl) {
      const m = unraid.mover || {};
      if (m.active) {
        moverEl.textContent = t('mgx.mover_active', 'Active ({count, plural, one {# file} other {# files}} left)', {
          count: m.remain_files || 0,
        });
        moverEl.style.color = 'var(--warn)';
      } else {
        moverEl.textContent = t('ui.idle', 'Idle');
        moverEl.style.color = 'var(--muted)';
      }
    }
  } else {
    setText('mgmt-generic-os', stats.os?.distro || stats.system?.os || stats.system?.distro || 'Linux');
    setText('mgmt-generic-engine', stats.storage?.engine || 'Btrfs / OpenZFS');
  }

  setText('mgmt-generic-cpu', processorWords(stats.cpu));
  if (stats.cpu?.governor) setText('mgmt-cpu-gov', powerModeWord(stats.cpu.governor));
  if (stats.motherboard) {
    setText('mgmt-board-name', `${stats.motherboard.vendor || ''} ${stats.motherboard.board || 'Standard PC'}`.trim());
    const bDate = stats.motherboard.bios_date ? ` (${stats.motherboard.bios_date})` : '';
    setText('mgmt-bios-ver', `${stats.motherboard.bios_version || '—'}${bDate}`);
  }
  if (stats.gpu) setText('mgmt-gpu-line', graphicsWords(stats.gpu));

  // NPU Neural Acceleration Engine
  if (stats.npu) {
    const npuContainer = document.getElementById('mgmt-npu-container');
    const npuBadge = document.getElementById('mgmt-npu-status-badge');
    const npuNameEl = document.getElementById('mgmt-npu-name');
    const npuDriverEl = document.getElementById('mgmt-npu-driver');
    const npuNodeEl = document.getElementById('mgmt-npu-node');
    const npuClockEl = document.getElementById('mgmt-npu-clock');
    const npuAccelEl = document.getElementById('mgmt-npu-accel');
    const npuFrameworksEl = document.getElementById('mgmt-npu-frameworks-list');

    if (npuContainer) {
      npuContainer.style.display = stats.npu.present ? 'block' : 'none';
    }
    if (npuBadge) {
      if (stats.npu.ready) {
        npuBadge.textContent = t('mgx.npu_active', 'NPU ACTIVE');
        npuBadge.style.color = '#c084fc';
        npuBadge.style.borderColor = 'rgba(168,85,247,0.35)';
      } else {
        npuBadge.textContent = t('mgx.npu_offline', 'NPU OFFLINE');
        npuBadge.style.color = 'var(--muted)';
        npuBadge.style.borderColor = 'rgba(255,255,255,0.1)';
      }
    }
    if (npuNameEl) npuNameEl.textContent = stats.npu.model || t('mgx.no_npu', 'No NPU Detected');
    if (npuDriverEl)
      npuDriverEl.textContent = t('mgx.driver', 'Driver: {name}', { name: stats.npu.driver || t('mgx.none', 'none') });
    if (npuNodeEl) {
      npuNodeEl.textContent = stats.npu.render_node || t('mgx.no_node', 'No node');
      npuNodeEl.style.display = stats.npu.render_node ? 'inline-block' : 'none';
    }
    if (npuClockEl) {
      const maxF = stats.npu.max_freq_mhz || 0;
      npuClockEl.textContent = maxF > 0 ? `${maxF} MHz` : t('mgx.dynamic_clock', 'Dynamic Clock');
    }
    if (npuAccelEl) npuAccelEl.textContent = stats.npu.acceleration || t('mgx.ai_ready', 'AI Acceleration Ready');
    if (npuFrameworksEl && Array.isArray(stats.npu.frameworks)) {
      if (stats.npu.frameworks.length > 0) {
        npuFrameworksEl.innerHTML = stats.npu.frameworks
          .map(
            (f) =>
              `<span class="gpu-codec-tag" style="background:rgba(168,85,247,0.12); color:var(--kb-text-ai); border-color:rgba(168,85,247,0.25);">${escapeHtml(f)}</span>`
          )
          .join('');
      } else {
        npuFrameworksEl.innerHTML = `<span class="gpu-codec-tag mgx-muted-box">${t('mgx.cpu_fallback', 'CPU Fallback')}</span>`;
      }
    }
  }

  // Update Docker pill in Hub and Left Sidebar
  if (stats.docker && Array.isArray(stats.docker)) {
    const runningCount = stats.docker.filter((c) => c.state === 'running').length;
    const dockPill = document.getElementById('mgmt-hub-docker-pill');
    if (dockPill) dockPill.textContent = t('dk.active', '{count} running', { count: runningCount });
    const sideDockBadge = document.getElementById('mgmt-sidebar-docker-badge');
    if (sideDockBadge) {
      sideDockBadge.textContent = t('dk.active', '{count} running', { count: runningCount });
      sideDockBadge.style.display = 'inline-block';
    }
  }

  // Update Storage pill in Hub and Left Sidebar
  if (stats.disks && Array.isArray(stats.disks)) {
    const storagePill = document.getElementById('mgmt-hub-storage-pill');
    if (storagePill)
      storagePill.textContent = t('mgx.drives', '{count, plural, one {# Drive} other {# Drives}}', {
        count: stats.disks.length,
      });
    const sideStorageBadge = document.getElementById('mgmt-sidebar-storage-badge');
    if (sideStorageBadge) {
      sideStorageBadge.textContent = t('mgx.drives', '{count, plural, one {# Drive} other {# Drives}}', {
        count: stats.disks.length,
      });
      sideStorageBadge.style.display = 'inline-block';
    }

    // Live update Disks Inventory table if currently rendered
    const diskTbody = document.getElementById('mgmt-disks-inventory-tbody');
    if (diskTbody) {
      const existingRows = diskTbody.querySelectorAll('tr[data-dev]');
      if (existingRows.length > 0) {
        stats.disks.forEach((d) => {
          const devName = d.dev || d.name;
          if (!devName) return;
          const row = diskTbody.querySelector(`tr[data-dev="${devName}"]`);
          if (row) {
            const isStandby = Boolean(d.standby || d.health === 'standby');
            const thermal = getThermalLevel(d.temp, isStandby, isNvmeDrive(d));
            const healthStr = isStandby ? 'STANDBY' : d.health ? String(d.health).toUpperCase() : 'OK';

            const healthTag = row.querySelector('.bay-health-tag');
            if (healthTag) {
              healthTag.className = `bay-health-tag ${thermal.cls}`;
              healthTag.textContent = healthStr;
            }
            const tempPill = row.querySelector('.bay-temp-pill');
            if (tempPill) {
              tempPill.style.color = thermal.color;
              tempPill.style.borderColor = thermal.color;
              tempPill.textContent = thermal.text;
            }
            const sizeTd = row.children[3];
            if (sizeTd && (d.size_formatted || d.size)) {
              sizeTd.textContent = d.size_formatted || d.size;
            }
          }
        });
      }
    }
  }

  // Update Network pill in Hub and Left Sidebar
  if (stats.net || stats.ip || stats.network) {
    let ifaceLabel = 'Online';
    if (stats.network?.interfaces && Array.isArray(stats.network.interfaces)) {
      const activePhys = stats.network.interfaces.filter((i) => {
        const isUp = i.operstate === 'up' || i.carrier === 1;
        const isVirtual = /^(lo|docker\d*|veth|br-|virbr|tailscale|wg\d*)/i.test(i.iface || i.name || '');
        return isUp && !isVirtual;
      });
      if (activePhys.length > 0) {
        ifaceLabel = `${activePhys.length} Active`;
      } else if (stats.net?.iface) {
        ifaceLabel = stats.net.iface.toUpperCase();
      }
    } else if (stats.net?.iface) {
      ifaceLabel = stats.net.iface.toUpperCase();
    }

    const netPill = document.getElementById('mgmt-hub-net-pill');
    if (netPill) netPill.textContent = ifaceLabel;
    const sideNetBadge = document.getElementById('mgmt-sidebar-net-badge');
    if (sideNetBadge) {
      sideNetBadge.textContent = ifaceLabel;
      sideNetBadge.style.display = 'inline-block';
    }
  }

  // Update Virtual Machines pill in Hub and Left Sidebar
  if (stats.vms && Array.isArray(stats.vms)) {
    const runningCount = stats.vms.filter((v) => v.state === 'running').length;
    const vmsPill = document.getElementById('mgmt-hub-vms-pill');
    if (vmsPill) vmsPill.textContent = t('mgx.running', '{count} Running', { count: runningCount });
    const sideVmsBadge = document.getElementById('mgmt-sidebar-vms-badge');
    if (sideVmsBadge) {
      sideVmsBadge.textContent = t('mgx.vms', '{count, plural, one {# VM} other {# VMs}}', { count: stats.vms.length });
      sideVmsBadge.style.display = stats.vms.length > 0 ? 'inline-block' : 'none';
    }
  }

  // Update UPS pill, sidebar badge, and telemetry if active
  if (stats.ups) {
    renderUpsTelemetry(stats.ups);
  }

  if (stats.fan_control && stats.fan_control.profile) {
    const prof = stats.fan_control.profile.toLowerCase();
    // a mode the Fans tab set (Full, or a speed by hand) highlights nothing here (Hardware 6)
    if (prof !== _activeProfile) {
      _activeProfile = prof;
      document.querySelectorAll('.profile-btn').forEach((b) => {
        const isAct = b.dataset.profile === prof;
        b.classList.toggle('active', isAct);
        b.setAttribute('aria-checked', isAct ? 'true' : 'false');
      });
    }
    const currentPill = document.getElementById('unraid-profile-current-pill');
    if (currentPill) {
      currentPill.textContent = t('hw.mode_now', 'Now: {mode}', { mode: modeName(prof, stats.fan_control.manual_pct) });
      currentPill.style.color = prof === 'auto' ? 'var(--ok2)' : 'var(--c-muted)';
    }
  }

  // Peripheral Auto-Hiding (AGENTS.md §1.1)
  const hasLcd =
    Boolean(stats?.peripherals?.fb_active) ||
    Boolean(stats?.hardware?.has_lcd) ||
    Boolean(stats?.lcd?.page !== undefined);
  const hasLed =
    Boolean(stats?.peripherals?.led_ready) ||
    Boolean(stats?.hardware?.has_mcu) ||
    Boolean(stats?.peripherals?.led_port);

  renderCoolingStatus(stats); // the Hardware page's "Now" list (Hardware 2, the status sentence)
  // a section is hidden on a machine without that hardware (Hardware 2: one page, no tabs)
  document.getElementById('mgmt-pane-hardware-led')?.classList.toggle('hw-absent', !hasLed);
  document.getElementById('mgmt-pane-hardware-lcd')?.classList.toggle('hw-absent', !hasLcd);
  showSystemFans(stats);
}

/**
 * What the Hardware page draws when it opens: the fan, light and copy controls in their sections, the
 * night card, the On/Off rows and the live status. The Hardware panel (hardware-drawer.js) runs it too.
 */
export function prepareHardwarePage() {
  restoreHardwareTabsToManagement();
  import('./quiet-night-card.js').then((m) => m.renderQuietNightCard()).catch(() => {}); // hardware extra
  import('./front-panel.js').then((m) => m.renderHardwarePower()).catch(() => {}); // On/Off first (Hardware 2)
  if (state.lastStats || state.latestStats) updateManagementTelemetry(state.lastStats || state.latestStats);
}

/** Fans the system drives (a kernel thermal governor, as on the Zettlab D4): readings only. */
export function showSystemFans(stats) {
  const fans = Array.isArray(stats?.fans) ? stats.fans : [];
  const system = stats?.fan_control?.driver_mode === 'none' && fans.some((rpm) => rpm > 0);
  const note = document.getElementById('hw-fans-system-note');
  if (note) note.hidden = !system;
  for (const sel of ['#mgmt-pane-unraid .profile-switcher-row', '#quiet-night-card', '#mgmt-pane-hardware-fans-slot']) {
    const el = document.querySelector(sel);
    if (el) el.inert = system;
  }
}

/** The Host tab's cooling mode: shown at once, saved, and put back to the real mode if refused. */
export async function chooseHostMode(p, btn, profileBtns) {
  _activeProfile = p;
  profileBtns.forEach((b) => {
    const isAct = b === btn;
    b.classList.toggle('active', isAct);
    b.setAttribute('aria-checked', isAct ? 'true' : 'false');
  });
  const pill = document.getElementById('unraid-profile-current-pill');
  if (pill) pill.textContent = t('hw.mode_now', 'Now: {mode}', { mode: modeName(p) });
  try {
    await api.post('/api/system/profile', { profile: p });
    showToast(t('toast.system_profile_switched', 'Cooling: {profile}.', { profile: modeName(p) }), 'success');
  } catch (err) {
    _activeProfile = null; // the next live reading puts back the mode the fans really have
    showToast(
      t('toast.failed_to_switch_profile', 'The cooling mode was not changed: {error}', { error: err.message }),
      'error'
    );
  }
}

/** The panes a tab shows: its data-tab-panes (Appearance's Look and Desktop hold several, APP-C), or its target. */
export function tabPanes(tab) {
  const list = tab?.dataset?.tabPanes;
  return list ? list.split(/\s+/).filter(Boolean) : [tab?.dataset?.tabTarget].filter(Boolean);
}

/** The tab of a card that shows paneId, so a link to any pane of Look or Desktop opens its tab. */
export function tabForPane(card, paneId) {
  return [...card.querySelectorAll('.mgmt-inner-tab')].find((t) => tabPanes(t).includes(paneId)) || null;
}

/** Shows the panes of one tab and hides the card's others. */
export function showPanes(card, panes) {
  card.querySelectorAll('.mgmt-tab-pane').forEach((p) => {
    const isMatch = panes.includes(p.id) || (p.id === 'mgmt-pane-docker' && panes.includes('mgmt-pane-docker-catalog'));
    p.style.display = isMatch ? (p.id === 'mgmt-pane-ai-chat' ? 'flex' : 'block') : 'none';
  });
}

export function initManagement() {
  window.__updateManagementTelemetry = updateManagementTelemetry;
  // the Kib window loads on first use (AI decision 1)
  /** @type {any} */ (window).openKibWindow = (pane) => import('./kib-window.js').then((m) => m.openKibWindow(pane));
  if (
    state.isLcdDirect ||
    (typeof window !== 'undefined' && window.location.search.includes('mode=lcd')) ||
    (document.body && document.body.classList.contains('lcd-direct'))
  ) {
    return;
  }

  const overlay = document.getElementById('management-modal-overlay');
  const win = document.getElementById('management-window');
  const header = document.getElementById('management-window-header');
  // on a phone the tab strip and a few wide tables scroll sideways: they say so at the edge
  watchSideScrollIn(win);
  const hubView = document.getElementById('management-hub-view');
  const detailContainer = document.getElementById('management-detail-container');
  const backBtn = document.getElementById('management-back-btn');
  const titleText = document.getElementById('management-header-title-text');
  const headerNav = document.getElementById('management-header-nav');
  const desktopIcon = document.getElementById('management-desktop-icon');
  const secBadge = document.getElementById('mgmt-hub-sec-badge');

  if (!overlay || !win) return;

  // Make Management window draggable by its header
  if (header) {
    makeDraggable(win, header, 'management');
  }

  win.addEventListener(
    'pointerdown',
    () => {
      bringToFront(win);
      saveOpenWindowsState();
    },
    { capture: true }
  );

  win.addEventListener('mousedown', () => {
    bringToFront(win);
    saveOpenWindowsState();
  });

  // Minimize button
  const minBtn = document.getElementById('management-min');
  if (minBtn) {
    const handleMin = (e) => {
      if (e && e.type === 'touchend') {
        e.preventDefault();
        e.stopPropagation();
      }
      DockManager.minimize('management');
    };
    minBtn.addEventListener('click', handleMin);
    minBtn.addEventListener('touchend', handleMin);
  }

  // Maximize button
  const maxBtn = document.getElementById('management-max');
  let _isMaximized = false;
  let _preMaxBounds = null;
  let _lastMgmtTouchTs = 0;
  if (maxBtn) {
    const handleMax = (e) => {
      if (e) {
        if (e.type === 'click' && Date.now() - _lastMgmtTouchTs < 450) {
          e.preventDefault();
          e.stopPropagation();
          return;
        }
        if (e.type === 'touchend') {
          _lastMgmtTouchTs = Date.now();
        }
        e.preventDefault();
        e.stopPropagation();
      }
      if (!_isMaximized) {
        _preMaxBounds = {
          left: win.style.left,
          top: win.style.top,
          transform: win.style.transform,
          width: win.style.width,
          height: win.style.height,
        };
        win.style.left = '16px';
        win.style.top = '56px';
        win.style.transform = 'none';
        win.style.width = 'calc(100vw - 32px)';
        win.style.height = 'calc(100vh - 128px)';
        win.dataset.snapped = 'maximize';
        _isMaximized = true;
        saveWindowBounds('management', {
          left: 16,
          top: 56,
          width: window.innerWidth - 32,
          height: window.innerHeight - 128,
          snapped: 'maximize',
        });
        saveOpenWindowsState();
      } else {
        win.dataset.snapped = '';
        if (_preMaxBounds) {
          win.style.left = _preMaxBounds.left;
          win.style.top = _preMaxBounds.top;
          win.style.transform = _preMaxBounds.transform;
          win.style.width = _preMaxBounds.width;
          win.style.height = _preMaxBounds.height;
        } else {
          win.style.left = '50%';
          win.style.top = '50%';
          win.style.transform = 'translate(-50%, -50%)';
          win.style.width = '';
          win.style.height = '';
        }
        _isMaximized = false;
        saveWindowBounds('management', {
          left: Math.round(window.innerWidth / 2 - 450),
          top: Math.round(window.innerHeight / 2 - 300),
          width: 900,
          height: 600,
          snapped: '',
        });
        saveOpenWindowsState();
      }
    };
    maxBtn.addEventListener('click', handleMax);
    maxBtn.addEventListener('touchend', handleMax);
  }

  // Close button
  const closeBtn = document.getElementById('management-close');
  if (closeBtn) {
    const handleClose = (e) => {
      if (e && e.type === 'touchend') {
        e.preventDefault();
        e.stopPropagation();
      }
      overlay.classList.remove('open');
      overlay.style.setProperty('display', 'none', 'important');
      win.classList.remove('window-focus-pulse');
      win.classList.add('window-minimized');
      if (_unbindMgmtTrap) {
        _unbindMgmtTrap();
        _unbindMgmtTrap = null;
      }
      DockManager.unregister('management');
    };
    closeBtn.addEventListener('click', handleClose);
    closeBtn.addEventListener('touchend', handleClose);
  }

  function showHub() {
    const earlyStyle = document.getElementById('kiboto-mgmt-early-style');
    if (earlyStyle) earlyStyle.remove();
    renderStatusSummary(); // UX-1: what needs attention comes first
    if (hubView) hubView.style.display = 'grid';
    if (detailContainer) detailContainer.style.display = 'none';
    if (headerNav) headerNav.style.display = 'none';
    if (backBtn) backBtn.style.display = 'none';
    if (titleText) titleText.textContent = t('mgmt.title', 'Settings');
    titleIconOf('');
    document.querySelectorAll('.mgmt-category-tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.mgmt-sidebar-item').forEach((b) => {
      b.classList.toggle('active', b.dataset.mgmtTarget === 'management-hub-view');
    });
    markCurrent(document.querySelectorAll('.mgmt-sidebar-item'), (b) => b.dataset.mgmtTarget === 'management-hub-view');
    document.querySelectorAll('.mgmt-detail-card').forEach((c) => (c.style.display = 'none'));
    if (detailContainer) {
      detailContainer.classList.remove('ai-active');
    }
    const contentPane = document.getElementById('mgmt-content-pane');
    if (contentPane) {
      contentPane.classList.remove('ai-active');
      contentPane.classList.remove('has-subnav');
    }
    saveOpenWindowsState();
  }

  function triggerSubTabLoad(paneId, subTabId = null) {
    if (paneId === 'mgmt-pane-widgets') {
      if (typeof syncWidgetSettingsUI === 'function') syncWidgetSettingsUI();
    } else if (paneId === 'mgmt-pane-dock') {
      if (typeof window.initDockSettingsControls === 'function') {
        window.initDockSettingsControls();
      }
    } else if (paneId === 'mgmt-pane-screensaver') {
      if (typeof window.initScreensaverSettingsControls === 'function') {
        window.initScreensaverSettingsControls();
      }
    } else if (paneId === 'mgmt-pane-theme') {
      if (typeof syncDesktopThemeUI === 'function') syncDesktopThemeUI();
    } else if (paneId === 'mgmt-pane-language') {
      const select = /** @type {HTMLSelectElement} */ (document.getElementById('mgmt-lang-select'));
      if (select && typeof getLanguage === 'function') {
        select.value = getLanguage();
      }
      if (typeof window.initTimezoneControls === 'function') {
        window.initTimezoneControls();
      }
    } else if (paneId === 'mgmt-pane-calendar') {
      if (typeof window.initCalendarView === 'function') {
        window.initCalendarView();
      }
    } else if (paneId === 'mgmt-pane-metrics') {
      import('./right-now.js').then((m) => m.installRightNow()).catch(() => {}); // SET-27 Activity 3
      // the chart's code loads when its page opens: it came with Settings, in the first seconds
      // after sign-in, and took the page over its download budget
      setTimeout(() => import('./metrics-chart.js').then((m) => m.showMetricsPage()), 50);
    } else if (paneId === 'mgmt-pane-copy') {
      fetchAndRenderCopyHistory();
    } else if (paneId === 'mgmt-pane-network' || paneId === 'mgmt-pane-network-physical') {
      loadNetworkPage();
    } else if (paneId === 'mgmt-pane-network-wireguard') {
      // COMP-01: the guided "Use from anywhere" card above the Tailscale details
      import('./remote-access.js')
        .then((m) => m.installRemoteAccess(document.getElementById('remote-access-mount')))
        .catch(() => {});
      import('./ddns-card.js').then((m) => m.renderDdnsCard()).catch(() => {}); // Dynamic DNS (audit A8)
      import('./https-card.js').then((m) => m.renderHttpsCard()).catch(() => {}); // HTTPS at home (audit A9)
      fetchAndRenderTailscaleDetails();
    } else if (paneId === 'mgmt-pane-unraid') {
      if (state.lastStats) updateManagementTelemetry(state.lastStats);
    } else if (paneId === 'mgmt-pane-hardware-lcd') {
      if (typeof restoreHardwareTabsToManagement === 'function') restoreHardwareTabsToManagement();
      setTimeout(() => {
        fitMiniPreviewScale();
        syncMiniPreviewTelemetry();
      }, 50);
    } else if (paneId === 'mgmt-pane-hardware-fans') {
      if (typeof restoreHardwareTabsToManagement === 'function') restoreHardwareTabsToManagement();
      import('./management/hw-helper.js').then((m) => m.loadHwHelperCard()).catch(() => {}); // SEC-24
    } else if (paneId === 'mgmt-pane-hardware-led') {
      if (typeof restoreHardwareTabsToManagement === 'function') restoreHardwareTabsToManagement();
    } else if (paneId === 'mgmt-pane-hardware-copy') {
      if (typeof restoreHardwareTabsToManagement === 'function') restoreHardwareTabsToManagement();
    } else if (paneId === 'mgmt-pane-chassis-twin') {
      import('./storage-summary.js').then((m) => m.renderStorageSummary()).catch(() => {}); // SET-22 Storage 3
      const mount = document.getElementById('mgmt-chassis-twin-mount');
      if (mount) fetchAndRenderChassisTwin(mount);
    } else if (paneId === 'mgmt-pane-storage-topo') {
      const mount = document.getElementById('mgmt-storage-topo-mount');
      if (mount) fetchAndRenderStorageTopology(mount);
    } else if (paneId === 'mgmt-pane-storage-shares') {
      const mount = document.getElementById('mgmt-storage-shares-mount');
      if (mount) fetchAndRenderNetworkShares(mount);
      const ef = document.getElementById('encrypted-folders-mount');
      if (ef) import('./encrypted-folders.js').then((m) => m.renderEncryptedFolders(ef)); // FEAT-13
    } else if (paneId === 'mgmt-pane-storage-remotes') {
      const mount = document.getElementById('mgmt-storage-remotes-mount');
      if (mount) fetchAndRenderRemoteStorage(mount);
    } else if (paneId === 'mgmt-pane-storage-disks') {
      fetchAndRenderDisksInventory();
    } else if (paneId === 'mgmt-pane-backups') {
      // replication sits in Backup -> More where this NAS can replicate (SET-22 Storage 3)
      import('./management/network.js')
        .then((n) => n.revealReplicationTab())
        .then((shown) => {
          if (shown) fetchAndRenderReplication();
        })
        .catch(() => {});
      // phone backup sits with the other backups (UX-26)
      import('./phone-backup.js')
        .then((p) => p.installPhoneBackup(document.getElementById('phone-backup-mount')))
        .catch(() => {});
      loadBackupExtras();
      loadBackupPane(); // what is folded loads when it is opened (SET-21, B13)
    } else if (paneId === 'mgmt-pane-security') {
      loadSecurityPane(); // an administrator's set-up only for administrators (SET-03)
      import('./firewall-card.js').then((m) => m.renderFirewallCard()).catch(() => {}); // firewall (audit A13)
    } else if (paneId === 'mgmt-pane-notifications') {
      loadNotificationsPane();
    } else if (paneId === 'mgmt-pane-connections') {
      loadConnectionsPane();
    } else if (paneId === 'mgmt-pane-account') {
      loadAccountPane();
    } else if (paneId === 'mgmt-pane-users') {
      import('./users.js').then((m) => m.loadUsersPane(subTabId || 'users-pane-list'));
    } else if (paneId === 'mgmt-pane-about') {
      fetchAndRenderSystemAbout();
      import('./front-panel.js').then((m) => m.renderFrontPanel()).catch(() => {}); // SET-30, decision 2 a
      import('./update-mark.js').then((m) => m.refreshUpdateMark()).catch(() => {}); // the daily check's switch
    } else if (paneId === 'mgmt-pane-vms-list' || paneId === 'mgmt-pane-vms-create' || paneId === 'mgmt-pane-vms-kvm') {
      fetchAndRenderMgmtVms();
    } else if (paneId === 'mgmt-pane-hardware-ups') {
      if (typeof fetchAndRenderUpsTelemetry === 'function') fetchAndRenderUpsTelemetry();
    } else if (
      paneId === 'mgmt-pane-ai-rag' ||
      paneId === 'mgmt-pane-ai-chat' ||
      paneId === 'mgmt-pane-ai-visual' ||
      paneId === 'mgmt-pane-ai-index'
    ) {
      if (kibPaneFor(paneId) !== paneId) {
        // Configuration is for people who manage Kib (SET-04)
        /** @type {any} */ (window).openKibWindow('mgmt-pane-ai-chat'); // Ask Kib is in its own window now (AI decision 1)
        return;
      }
      fetchAndRenderAiStatus();
      loadKibExtras(paneId);
      if (paneId === 'mgmt-pane-ai-rag' || paneId === 'mgmt-pane-ai-visual') {
        const q = _getActiveAiSearchQuery();
        if (q || _aiSelectedColor || _aiSelectedScene) {
          runAiVisualSearch(q);
        } else {
          _renderAiRagInitialEmptyState();
        }
      } else if (paneId === 'mgmt-pane-ai-chat') {
        const chatInput = document.getElementById('ai-chat-input');
        if (chatInput) setTimeout(() => chatInput.focus(), 50);
      }
    }
  }

  async function fetchAndRenderMgmtVms() {
    const grid = document.getElementById('mgmt-vms-grid');
    const empty = document.getElementById('mgmt-vms-empty');
    const strip = document.getElementById('mgmt-vms-summary-strip');
    const kvmBody = document.getElementById('mgmt-vms-kvm-body');
    if (!grid && !strip) return;

    try {
      let listError = '';
      const [tel, list] = await Promise.all([
        api.get('/api/vms/telemetry').catch(() => null),
        api.get('/api/vms').catch((e) => {
          listError = (e && e.message) || 'error';
          return [];
        }),
      ]);

      const vmsList = Array.isArray(list) ? list : [];
      const runningCount = vmsList.filter((v) => v.state === 'running').length;
      const hubPill = document.getElementById('mgmt-hub-vms-pill');
      if (hubPill) hubPill.textContent = t('mgx.running', '{count} Running', { count: runningCount });
      const sideBadge = document.getElementById('mgmt-sidebar-vms-badge');
      if (sideBadge) {
        sideBadge.textContent = t('mgx.vms', '{count, plural, one {# VM} other {# VMs}}', { count: vmsList.length });
        sideBadge.style.display = vmsList.length > 0 ? 'inline-block' : 'none';
      }

      if (strip) {
        const kvmActive = tel?.kvm?.state === 'active';
        // no answer is not "Software Emulation" in red: it was not checked (VMs report 16)
        const kvmColor = !tel?.kvm
          ? 'var(--muted)'
          : kvmActive
            ? 'var(--ok2, #33cdb8)'
            : tel.kvm.state === 'restricted'
              ? 'var(--warn, #f5a623)'
              : 'var(--danger, #ff6b6b)';
        // without KVM machines run emulated: say "slow mode", not a technical badge (VMs decision 4 a)
        const kvmBadge = !tel?.kvm
          ? t('mvm.not_checked', 'Could not be checked')
          : kvmActive
            ? tel.kvm.badge || 'KVM Acceleration Active'
            : t('mvm.slow_mode', 'Slow mode: no hardware virtualization');
        const slowFix = tel?.kvm && !kvmActive && tel.kvm.remediation ? tel.kvm.remediation : '';
        // the server sends memory_budget and cpu_capacity; the old keys never came, so these boxes said
        // "Dynamic" and "Optimal" on every NAS (VMs report 15-16). Unknown values are left out.
        const budget = tel?.memory_budget || {};
        const cpuCap = tel?.cpu_capacity || {};
        const headroom =
          typeof budget.safe_headroom_gb === 'number'
            ? t('mvm.mem_left', '{gb} GB', { gb: formatFixed(budget.safe_headroom_gb, 1) })
            : '';
        const threadsUsed = cpuCap.host_threads
          ? t('mvm.threads_used', '{used} of {total}', {
              used: cpuCap.allocated_vcpus || 0,
              total: cpuCap.host_threads,
            })
          : '';

        strip.innerHTML = `
          <div class="mgx-box">
            <div class="mgx-xs-bold-muted">${t('mvm.engine', 'Hypervisor')}</div>
            <div style="font-size: 13px; font-weight: 700; color: ${kvmColor}; margin-top: 4px; display: flex; align-items: center; gap: 6px;">
              <span aria-hidden="true">⚡</span> <span>${escapeHtml(kvmBadge)}</span>
            </div>
            ${slowFix ? `<div class="vm-slow-fix">${escapeHtml(t('mvm.slow_fix', 'Machines still start, slowly. To fix it: {fix}', { fix: slowFix }))}</div>` : ''}
          </div>
          ${
            headroom
              ? `<div class="mgx-box">
            <div class="mgx-xs-bold-muted">${t('mvm.mem_left_label', 'Memory left for machines')}</div>
            <div style="font-size: 13px; font-weight: 700; color: var(--lt-ink-brand, var(--accent-cyan, #33cdb8)); margin-top: 4px;">
              ${escapeHtml(headroom)}
            </div>
          </div>`
              : ''
          }
          ${
            threadsUsed
              ? `<div class="mgx-box">
            <div class="mgx-xs-bold-muted">${t('mvm.threads_used_label', 'Processor threads in use')}</div>
            <div class="mgx-fs13-bold-strong">
              ${escapeHtml(threadsUsed)}
            </div>
          </div>`
              : ''
          }
        `;
      }

      if (grid) {
        if (listError) {
          // a failed or refused list is not an empty one (VMs report 16)
          if (empty) empty.style.display = 'none';
          grid.innerHTML = `<div class="vml-muted-box mgmt-vms-failed" role="alert">
            <div class="vml-semi-strong">${escapeHtml(t('mvm.load_failed', 'The virtual machines could not be loaded.'))}</div>
            <div class="vml-xs">${escapeHtml(listError)}</div>
            <button type="button" class="btn-pill-toggle" id="mgmt-vms-retry">${escapeHtml(t('mvm.try_again', 'Try again'))}</button>
          </div>`;
          grid
            .querySelector('#mgmt-vms-retry')
            ?.addEventListener('click', () => window.dispatchEvent(new Event('vm-updated')));
        } else if (vmsList.length === 0) {
          grid.innerHTML = '';
          if (empty) empty.style.display = 'block';
        } else {
          if (empty) empty.style.display = 'none';
          // VMs decision 2 (owner, 16 Nov): Settings shows status, one line per machine; starting, stopping
          // and changing machines happen in the VM window only (two lists with different buttons and words)
          const stateWord = (vm) =>
            isShuttingDown(vm)
              ? t('vmp.st_shutting', 'Shutting down')
              : vm.state === 'running'
                ? t('mvm.st_running', 'Running')
                : vm.state === 'paused'
                  ? t('mvm.st_paused', 'Paused')
                  : t('mvm.st_stopped', 'Stopped');
          grid.innerHTML = `<ul class="mgmt-vm-lines">${vmsList
            .map((vm) => {
              const ramGb = vm.ram_gb
                ? `${vm.ram_gb} GB`
                : vm.memory_mb
                  ? vm.memory_mb >= 1024
                    ? `${formatFixed(vm.memory_mb / 1024, 0)} GB`
                    : `${vm.memory_mb} MB`
                  : '1 GB';
              const cores = vm.vcpus || vm.cores || 1;
              const osType = vm.os_family
                ? vm.os_family.charAt(0).toUpperCase() + vm.os_family.slice(1)
                : vm.os_type || 'Linux';
              return `<li class="mgmt-vm-card mgmt-vm-line is-${escapeHtml(vm.state || 'stopped')}" data-vm-id="${escapeHtml(vm.id)}">
                <div class="mgmt-vm-line-text">
                  <div class="mgx-fs13-bold-strong-2">${escapeHtml(vm.name || vm.id)}</div>
                  <div class="mgx-xs-muted">${escapeHtml(osType)} • ${cores} vCPU • ${ramGb} RAM</div>
                  ${slowNoteHtml(vm, tel?.kvm?.remediation || '')}
                </div>
                <span class="mgmt-vm-state">${escapeHtml(stateWord(vm))}</span>
              </li>`;
            })
            .join('')}</ul>
          <button type="button" class="btn-pill-toggle is-primary" id="mgmt-vms-open-window">${escapeHtml(t('mvm.open_window', 'Open the virtual machines window to start, stop or change them'))}</button>`;
          grid.querySelector('#mgmt-vms-open-window')?.addEventListener('click', () => {
            document.getElementById('btn-mgmt-vm-launch-window')?.click();
          });
        }
      }

      if (kvmBody && tel?.kvm) {
        kvmBody.innerHTML = `
          <div class="mgx-col-box">
            <div class="mgx-row">
              <div class="mgx-fs13-bold-strong-2">${t('mvm.virt_ext', 'Hardware Virtualization Extension')}</div>
              <span style="padding: 3px 8px; border-radius: 4px; font-size: var(--kb-fs-xs); font-weight: 700; background: ${tel.kvm.state === 'active' ? 'rgba(51,205,184,0.15)' : 'rgba(239,68,68,0.15)'}; color: ${tel.kvm.state === 'active' ? 'var(--ok2)' : 'var(--danger)'};">
                ${escapeHtml(tel.kvm.badge || 'KVM')}
              </span>
            </div>
            <div class="mgx-xs-muted-2">
              ${escapeHtml(tel.kvm.details || '')}
            </div>
            <div class="mgx-grid">
              ${
                tel.cpu_capacity?.host_threads
                  ? `<div class="mgx-box-2">
                <div class="mgx-xs-muted">${t('mvm.host_threads', 'CPU Host Threads')}</div>
                <div class="mgx-fs14-bold-strong">${t('mvm.threads', '{count, plural, one {# Thread} other {# Threads}}', { count: tel.cpu_capacity.host_threads })}</div>
              </div>`
                  : ''
              }
              ${
                typeof tel.vhost_net === 'boolean'
                  ? `<div class="mgx-box-2">
                <div class="mgx-xs-muted">${t('mvm.vhost', 'vhost-net Acceleration')}</div>
                <div class="${tel.vhost_net ? 'mgx-fs14-bold-ok' : 'mgx-fs14-bold-strong'}">${tel.vhost_net ? t('mvm.supported', 'Supported') : t('mvm.vhost_none', 'Not available')}</div>
              </div>`
                  : ''
              }
              ${
                Array.isArray(tel.bridges)
                  ? `<div class="mgx-box-2">
                <div class="mgx-xs-muted">${t('mvm.bridges', 'Network bridges')}</div>
                ${
                  tel.bridges.length
                    ? `<div class="mgx-fs14-bold-brand" translate="no">${escapeHtml(tel.bridges.join(' / '))}</div>`
                    : `<div class="mgx-fs14-bold-strong">${t('mvm.bridges_none', 'None found')}</div>`
                }
              </div>`
                  : ''
              }
            </div>
          </div>
        `;
      }
    } catch (err) {
      console.warn('Failed to load VM telemetry in Settings:', err);
    }
  }

  function showSection(targetId, specificPane = null, subTabId = null) {
    const earlyStyle = document.getElementById('kiboto-mgmt-early-style');
    if (earlyStyle) earlyStyle.remove();
    let desiredSubPane = specificPane;
    if (desiredSubPane === 'mgmt-pane-system') desiredSubPane = 'mgmt-pane-backups';
    if (!desiredSubPane && SUBPANE_MAP[targetId]) {
      desiredSubPane = SUBPANE_MAP[targetId].pane;
      targetId = SUBPANE_MAP[targetId].section;
    } else if (SUBPANE_MAP[targetId]) {
      targetId = SUBPANE_MAP[targetId].section;
    }
    const named = desiredSubPane ? document.getElementById(desiredSubPane) : null;
    const scrollTo = named && !named.classList.contains('mgmt-tab-pane') ? named : null; // a section of a one-page pane (SET-24)
    if (scrollTo) desiredSubPane = scrollTo.closest('.mgmt-tab-pane')?.id || desiredSubPane;
    const home = (scrollTo || named)?.closest('.mgmt-detail-card');
    if (home && home.id !== targetId) targetId = home.id; // a pane that moved to its own page
    if (targetId === 'mgmt-sec-docker' && typeof window.openContainersManager === 'function') {
      // Apps live in one place, the Apps window (UX-4)
      window.openContainersManager({ view: desiredSubPane === 'mgmt-pane-docker-catalog' ? 'catalog' : 'installed' });
      return false; // nothing changed here: the caller leaves Settings as it was
    }
    if (targetId === 'mgmt-sec-ai' && (KIB_WINDOW_PANES.has(desiredSubPane || '') || !mayManageKib())) {
      // Ask and Search live in the Kib window (AI decision 1); someone who may not change Kib's
      // settings gets the window too, instead of a page that is not theirs
      if (desiredSubPane === 'mgmt-pane-ai-visual') setAiVisualFiltersDrawerOpen(true);
      /** @type {any} */ (window).openKibWindow(
        KIB_WINDOW_PANES.has(desiredSubPane || '') ? desiredSubPane : 'mgmt-pane-ai-chat'
      );
      return false;
    }
    if (mayNotOpen(targetId, desiredSubPane)) {
      // this person's rights hide the page; a link, an alert or the page remembered from before
      // a reload opened it all the same (SET-12)
      showHub();
      return true;
    }
    if (desiredSubPane === 'mgmt-pane-ai-visual') {
      desiredSubPane = 'mgmt-pane-ai-rag';
      setAiVisualFiltersDrawerOpen(true);
    }

    if (hubView) hubView.style.display = 'none';
    const isAi = targetId === 'mgmt-sec-ai';
    if (detailContainer) {
      detailContainer.style.display = isAi ? 'flex' : 'block';
      detailContainer.style.flexDirection = isAi ? 'column' : '';
      detailContainer.style.height = isAi ? '100%' : '';
      detailContainer.classList.toggle('ai-active', isAi);
    }
    const contentPane = document.getElementById('mgmt-content-pane');
    if (contentPane) {
      contentPane.classList.toggle('ai-active', isAi);
      const activeCard = document.getElementById(targetId);
      const hasSubnav = activeCard ? !!activeCard.querySelector('.mgmt-sticky-subnav') : false;
      contentPane.classList.toggle('has-subnav', hasSubnav);
    }
    if (headerNav) headerNav.style.display = 'flex';
    if (backBtn) backBtn.style.display = 'inline-flex';

    document.querySelectorAll('.mgmt-detail-card').forEach((c) => {
      if (c.id === targetId) {
        c.style.display = c.id === 'mgmt-sec-ai' ? 'flex' : 'block';
        if (c.id === 'mgmt-sec-ai') {
          c.style.flexDirection = 'column';
          c.style.height = '100%';
        }
      } else {
        c.style.display = 'none';
      }
    });

    const targetTab = document.querySelector(`.mgmt-category-tab[data-mgmt-target="${targetId}"]`);
    document.querySelectorAll('.mgmt-category-tab').forEach((t) => t.classList.remove('active'));
    if (targetTab) targetTab.classList.add('active');

    const currentEntry = highlightEntry(targetId, desiredSubPane);
    if (currentEntry && typeof currentEntry.scrollIntoView === 'function') {
      try {
        currentEntry.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
      } catch (_) {}
    }

    let sectionName = t('mgmt.title', 'Settings');
    if (targetId === 'mgmt-sec-wallpaper') {
      sectionName = t('mgmt.appearance_title', 'Appearance');
    } else if (targetId === 'mgmt-sec-calendar') {
      sectionName = t('mgmt.sidebar_calendar', 'Calendar');
    } else if (targetId === 'mgmt-sec-activity') {
      sectionName = t('mgmt.activity_title', 'Activity');
    } else if (targetId === 'mgmt-sec-network') {
      sectionName = t('mgmt.network_sec_title', 'Network & Sharing');
      fetchAndRenderNetworkTopology();
    } else if (targetId === 'mgmt-sec-vms') {
      sectionName = t('mgmt.vms_title', 'Virtual Machines');
      fetchAndRenderMgmtVms();
    } else {
      if (targetId === 'mgmt-sec-hardware' || targetId === 'mgmt-sec-services') {
        sectionName = t('mgmt.sidebar_hardware', 'Hardware'); // the page's name, as in the sidebar
        prepareHardwarePage();
      } else if (targetId === 'mgmt-sec-away') {
        sectionName = t('mgmt.sidebar_away', 'Away from home');
      } else if (targetId === 'mgmt-sec-storage') {
        sectionName = t('mgmt.storage_title', 'Storage');
      } else if (targetId === 'mgmt-sec-shares') {
        sectionName = t('mgmt.sidebar_shared_folders', 'Shared folders');
      } else if (targetId === 'mgmt-sec-ups') {
        sectionName = t('mgmt.sidebar_ups', 'Power & Battery');
        fetchAndRenderUpsTelemetry();
        if (typeof loadUpsConfigToDrawer === 'function') loadUpsConfigToDrawer();
        import('./power-schedule-card.js').then((m) => m.renderPowerScheduleCard()).catch(() => {}); // audit A10
        import('./drive-sleep-card.js').then((m) => m.renderDriveSleepCard()).catch(() => {});
        import('./heat-shutdown-card.js').then((m) => m.renderHeatShutdownCard()).catch(() => {}); // hardware extra
      } else if (targetId === 'mgmt-sec-system-group') {
        sectionName = t('mgmt.system_title', 'System & Identity');
      } else if (targetId === 'mgmt-sec-ai') {
        sectionName = t('mgmt.sidebar_kib', 'Kib'); // the page's name (AI decision 8), as in the sidebar
        fetchAndRenderAiStatus();
      }
    }

    if (titleText) titleText.textContent = sectionName;
    titleIconOf(targetId);

    const parentCard = document.getElementById(targetId);
    if (parentCard) {
      if (desiredSubPane) {
        const paneTab = tabForPane(parentCard, desiredSubPane);
        parentCard.querySelectorAll('.mgmt-inner-tab').forEach((t) => {
          const isActive = paneTab ? t === paneTab : t.dataset.tabTarget === desiredSubPane;
          t.classList.toggle('active', isActive);
          t.setAttribute('aria-selected', isActive ? 'true' : 'false');
          if (isActive && typeof t.scrollIntoView === 'function') {
            const tabsContainer = t.closest('.mgmt-inner-tabs');
            if (tabsContainer && tabsContainer.scrollWidth > tabsContainer.clientWidth) {
              try {
                t.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
              } catch (_) {}
            }
          }
        });
        const panes = paneTab ? tabPanes(paneTab) : [desiredSubPane];
        showPanes(parentCard, panes);
        panes.forEach((p) => triggerSubTabLoad(p, p === desiredSubPane ? subTabId : null));
        // the section starts at the top, or at the pane the link names when it is not the tab's first
        const contentPane = parentCard.closest('.mgmt-content-pane') || document.querySelector('.mgmt-content-pane');
        if (contentPane) contentPane.scrollTop = 0;
        (scrollTo || (panes[0] !== desiredSubPane ? document.getElementById(desiredSubPane) : null))?.scrollIntoView?.({
          block: 'start',
        });
      } else {
        let activeTabBtn = parentCard.querySelector('.mgmt-inner-tab.active');
        if (!activeTabBtn) {
          activeTabBtn = parentCard.querySelector('.mgmt-inner-tab');
          if (activeTabBtn) activeTabBtn.classList.add('active');
        }
        if (activeTabBtn) {
          parentCard.querySelectorAll('.mgmt-inner-tab').forEach((t) => {
            const isActive = t === activeTabBtn;
            t.classList.toggle('active', isActive);
            t.setAttribute('aria-selected', isActive ? 'true' : 'false');
          });
          const panes = tabPanes(activeTabBtn);
          showPanes(parentCard, panes);
          panes.forEach((p, i) => triggerSubTabLoad(p, i === 0 ? subTabId : null));
        } else {
          const singlePane = parentCard.querySelector('.mgmt-tab-pane');
          if (singlePane) {
            singlePane.style.display = singlePane.id === 'mgmt-pane-ai-chat' ? 'flex' : 'block';
            triggerSubTabLoad(singlePane.id, subTabId);
          }
        }
      }
    }
    saveOpenWindowsState();
  }

  // Left sidebar items click listener

  document.querySelectorAll('.mgmt-inner-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const parentCard = tab.closest('.mgmt-detail-card');
      if (!parentCard) return;

      // Update tab buttons
      parentCard.querySelectorAll('.mgmt-inner-tab').forEach((t) => {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
      });
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');
      if (typeof tab.scrollIntoView === 'function') {
        const tabsContainer = tab.closest('.mgmt-inner-tabs');
        if (tabsContainer && tabsContainer.scrollWidth > tabsContainer.clientWidth) {
          try {
            tab.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
          } catch (_) {}
        }
      }

      // Update tab panes
      const targetPaneId = tab.dataset.tabTarget;
      const panes = tabPanes(tab);
      showPanes(parentCard, panes);

      // Reset scroll position to top of pane when switching sub-tabs
      const contentPane = tab.closest('.mgmt-content-pane') || document.querySelector('.mgmt-content-pane');
      if (contentPane && contentPane.scrollTop > 0) {
        contentPane.scrollTop = 0;
      }

      panes.forEach((p) => triggerSubTabLoad(p));
      highlightEntry(parentCard.id, targetPaneId); // "Users" and "Backup" are entries of their own (SET-12)
      saveOpenWindowsState();
    });
  });

  wireTablists(document.getElementById('management-window') || document);

  document.querySelectorAll('.mgmt-sidebar-item').forEach((item) => {
    item.addEventListener('click', () => {
      if (typeof item.scrollIntoView === 'function') {
        try {
          item.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
        } catch (_) {}
      }
      const targetId = item.dataset.mgmtTarget;
      if (item.dataset.mgmtAction === 'files') {
        if (typeof window.openFileManager === 'function') window.openFileManager();
        return;
      }
      if (item.dataset.mgmtAction === 'search') {
        // "Search settings" (X2): Spotlight finds pages and tabs; its own settings field comes with SET-20
        /** @type {any} */ (window).openSpotlight?.();
        return;
      }
      if (targetId === 'management-hub-view') {
        showHub();
      } else if (targetId) {
        showSection(targetId, item.dataset.mgmtPane || null);
      }
      saveOpenWindowsState();
    });
  });

  installAdvancedSwitch(); // "Show advanced tools": expert details and tools; it hides no page (X1)
  installSidebarGroups();
  installHealthSignal(); // the opt-in anonymous weekly report, last on General (SET-23)

  // Hub cards click listener
  document.querySelectorAll('.mgmt-app-card').forEach((card) => {
    card.addEventListener('click', () => {
      const targetId = card.dataset.mgmtTarget;
      if (targetId) {
        showSection(targetId);
        saveOpenWindowsState();
      }
    });
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation(); // the page-wide key handler clicks a role="button" too: the page opened twice
        const targetId = card.dataset.mgmtTarget;
        if (targetId) {
          showSection(targetId);
          saveOpenWindowsState();
        }
      }
    });
  });

  // Header quick tabs click listener
  document.querySelectorAll('.mgmt-category-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const targetId = tab.dataset.mgmtTarget;
      if (targetId) {
        showSection(targetId);
        saveOpenWindowsState();
      }
    });
  });

  // Back button click listener
  if (backBtn) {
    backBtn.addEventListener('click', () => {
      showHub();
      saveOpenWindowsState();
    });
  }

  // Global helper to open / focus Management window
  window.openManagementWindow = (sectionId = null, paneId = null, subTabId = null) => {
    if (sectionId) {
      // Apps live in their own window: a link to the old Apps section opened that window and
      // Settings together (SET-12)
      if (showSection(sectionId, paneId, subTabId) === false) return;
    } else {
      showHub();
    }

    if (!DockManager.windows['management']) {
      DockManager.register('management', overlay, '#i-management', 'Management');
    }
    if (DockManager.windows['management']) {
      DockManager.windows['management'].minimized = false;
      DockManager.windows['management'].closed = false;
    }
    DockManager.restore('management');
    overlay.style.removeProperty('display');
    overlay.style.display = 'flex';
    overlay.classList.add('open');
    win.classList.remove('window-minimized');
    win.style.removeProperty('display');

    if (state.latestStats) updateManagementTelemetry(state.latestStats);

    bringToFront(win);
    win.classList.remove('window-focus-pulse');
    void win.offsetWidth; // Reflow
    win.classList.add('window-focus-pulse');
    setTimeout(() => win.classList.remove('window-focus-pulse'), 850);

    if (_unbindMgmtTrap) {
      _unbindMgmtTrap();
    }
    // a window, not a modal: Tab may leave it; Esc closes it (UX-30)
    _unbindMgmtTrap = trapFocus(
      win,
      () => {
        const cBtn = document.getElementById('management-close');
        if (cBtn) cBtn.click();
      },
      { trap: false }
    );

    if (window.DockManager) {
      window.DockManager.render();
    }
  };

  // Explicit helper for section and subpane deep-linking
  window.openManagementSection = (sectionId, paneId = null, subTabId = null) => {
    window.openManagementWindow(sectionId, paneId, subTabId);
  };

  // Support window:open event bus deep-linking
  ZettEventBus.on('window:open', (payload) => {
    if (payload && (payload.id === 'management' || payload.id === 'management-window')) {
      window.openManagementWindow(payload.section || payload.pane, payload.pane, payload.subtab);
    }
  });

  // Desktop icon click listener
  if (desktopIcon) {
    desktopIcon.addEventListener('click', () => {
      window.openManagementWindow();
    });
    desktopIcon.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        window.openManagementWindow();
      }
    });
  }

  // Synchronize security alert badge on Security card and sidebar
  function syncSecurityBadge() {
    const defaultWarning = document.getElementById('sec-default-pwd-warning');
    const isWarning = defaultWarning && defaultWarning.style.display !== 'none';
    if (secBadge) {
      secBadge.style.display = isWarning ? 'flex' : 'none';
    }
    const sideSecBadge = document.getElementById('mgmt-sidebar-sec-badge');
    if (sideSecBadge) {
      sideSecBadge.style.display = isWarning ? 'inline-block' : 'none';
    }
  }

  const observer = new MutationObserver(syncSecurityBadge);
  const warnEl = document.getElementById('sec-default-pwd-warning');
  if (warnEl) {
    observer.observe(warnEl, { attributes: true, attributeFilter: ['style'] });
    syncSecurityBadge();
  }

  // Profile buttons listener and keyboard navigation
  const profileBtns = Array.from(document.querySelectorAll('.profile-btn'));
  profileBtns.forEach((btn, idx) => {
    btn.addEventListener('click', () => {
      const p = btn.dataset.profile;
      if (!p) return;
      const apply = () => chooseHostMode(p, btn, profileBtns);
      // a fixed speed does not follow the temperature: ask first (SET-15, Hardware 1)
      if (p in FIXED_PCT) askFixedSpeed(FIXED_PCT[p], apply);
      else apply();
    });

    btn.addEventListener('keydown', (e) => {
      let targetBtn = null;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        targetBtn = profileBtns[(idx + 1) % profileBtns.length];
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        targetBtn = profileBtns[(idx - 1 + profileBtns.length) % profileBtns.length];
      }
      if (targetBtn) {
        targetBtn.focus();
        targetBtn.click();
      }
    });
  });

  // Copy history refresh button
  const refreshHistoryBtn = document.getElementById('btn-refresh-copy-history');
  if (refreshHistoryBtn) {
    refreshHistoryBtn.addEventListener('click', () => {
      fetchAndRenderCopyHistory();
      showToast(t('toast.ingest_history_refreshed', 'Card copies refreshed.'), 'info');
    });
  }

  // Network topology refresh button & controls
  const refreshNetBtn = document.getElementById('btn-refresh-network-topology');
  if (refreshNetBtn) {
    refreshNetBtn.addEventListener('click', () => {
      fetchAndRenderNetworkTopology();
      showToast(t('toast.network_topology_refreshed', 'Network topology refreshed.'), 'info');
    });
  }
  initNetworkControls();

  // UPS telemetry refresh button & drawer controls
  // Refresh is wired once, by initUpsDrawerControls (two handlers gave two messages, SET-15)
  initUpsDrawerControls();

  // Virtual Machines refresh, launch window & create wizard buttons
  const refreshVmBtn = document.getElementById('btn-mgmt-vm-refresh');
  if (refreshVmBtn) {
    refreshVmBtn.addEventListener('click', () => {
      fetchAndRenderMgmtVms();
      showToast(t('toast.vm_fleet_refreshed', 'VM fleet refreshed.'), 'info');
    });
  }

  const launchVmWinBtn = document.getElementById('btn-mgmt-vm-launch-window');
  if (launchVmWinBtn) {
    launchVmWinBtn.addEventListener('click', () => {
      if (typeof window.openVmManager === 'function') window.openVmManager();
    });
  }

  const launchDockerWinBtn = document.getElementById('btn-mgmt-docker-launch-window');
  if (launchDockerWinBtn) {
    launchDockerWinBtn.addEventListener('click', () => {
      if (typeof window.openContainersManager === 'function') {
        window.openContainersManager();
      } else if (typeof window.openContainersWindow === 'function') {
        window.openContainersWindow();
      }
    });
  }

  const wireVmCreate = (btnId) => {
    const btn = document.getElementById(btnId);
    if (btn) {
      btn.addEventListener('click', () => {
        import('./vm-manager.js').then((m) => {
          if (typeof m.openVmCreateModal === 'function') m.openVmCreateModal();
        });
      });
    }
  };
  wireVmCreate('btn-mgmt-vm-create');
  wireVmCreate('btn-mgmt-vm-create-empty');
  wireVmCreate('btn-mgmt-vm-start-wizard');

  const btnIsoLibrary = document.getElementById('btn-mgmt-vm-iso-library');
  if (btnIsoLibrary && !btnIsoLibrary.dataset.bound) {
    btnIsoLibrary.dataset.bound = '1';
    btnIsoLibrary.addEventListener('click', async () => {
      const { openIsoManagerModal } = await import('./vm-manager.js');
      if (typeof openIsoManagerModal === 'function') {
        openIsoManagerModal('catalog');
      }
    });
  }

  // Hardware drawer shortcuts & cross-pillar navigators
  const btnOpenFans = document.getElementById('btn-open-fans-drawer');
  if (btnOpenFans) {
    btnOpenFans.addEventListener('click', () => {
      openDrawer('tab-fans');
    });
  }

  const btnOpenLed = document.getElementById('btn-open-led-drawer');
  if (btnOpenLed) {
    btnOpenLed.addEventListener('click', () => {
      openDrawer('tab-led');
    });
  }

  const btnOpenLcd = document.getElementById('btn-open-lcd-drawer');
  if (btnOpenLcd) {
    btnOpenLcd.addEventListener('click', () => {
      openDrawer('tab-layout');
    });
  }

  const btnOpenFullUps = document.getElementById('btn-open-full-ups-view');
  if (btnOpenFullUps) {
    btnOpenFullUps.addEventListener('click', () => {
      showSection('mgmt-sec-ups');
    });
  }

  const btnGotoShares = document.getElementById('btn-goto-storage-shares');
  if (btnGotoShares) {
    btnGotoShares.addEventListener('click', () => {
      showSection('mgmt-sec-shares', 'mgmt-pane-storage-shares');
    });
  }

  // Chassis digital twin refresh button
  const refreshChassisBtn = document.getElementById('btn-refresh-chassis');
  if (refreshChassisBtn) {
    refreshChassisBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-chassis-twin-mount');
      if (mount)
        refreshAndSay(
          () => fetchAndRenderChassisTwin(mount),
          t('toast.chassis_digital_twin_refreshed', 'Drive bays refreshed.')
        );
    });
  }

  // Storage pool topology refresh & create buttons
  const refreshTopoBtn = document.getElementById('btn-refresh-topo');
  if (refreshTopoBtn) {
    refreshTopoBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-topo-mount');
      if (mount)
        refreshAndSay(
          () => fetchAndRenderStorageTopology(mount),
          t('toast.storage_topology_refreshed', 'Storage topology refreshed.')
        );
    });
  }

  const createPoolBtn = document.getElementById('btn-create-storage-pool');
  if (createPoolBtn) {
    createPoolBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-topo-mount');
      openCreateStoragePoolModal(() => {
        if (mount) fetchAndRenderStorageTopology(mount);
      });
    });
  }

  // Network shares refresh & create buttons
  const refreshSharesBtn = document.getElementById('btn-refresh-shares');
  if (refreshSharesBtn) {
    refreshSharesBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-shares-mount');
      if (mount) fetchAndRenderNetworkShares(mount);
      showToast(t('toast.network_shares_refreshed', 'Network shares refreshed.'), 'info');
    });
  }

  // "Create Share" is wired by the share list (chassis-visualizer.js), which also hides it where
  // shares cannot be made; a second listener here opened the dialog twice per click (SET-14)

  // every link shared from this NAS, with "Stop sharing" (SET-01)
  const moveInBtn = document.getElementById('btn-move-in');
  if (moveInBtn) {
    moveInBtn.addEventListener('click', () => {
      import('./move-in.js').then((m) => m.openMoveIn()).catch(() => {});
    });
  }
  const sharedLinksBtn = document.getElementById('btn-show-shared-links');
  if (sharedLinksBtn) {
    sharedLinksBtn.addEventListener('click', () =>
      import('./shared-links.js').then((m) => m.openSharedLinks({ everyone: true }))
    );
  }

  // Remote & Cloud Storage refresh button
  const refreshRemotesBtn = document.getElementById('btn-refresh-remotes');
  if (refreshRemotesBtn) {
    refreshRemotesBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-remotes-mount');
      if (mount)
        refreshAndSay(
          () => fetchAndRenderRemoteStorage(mount),
          t('toast.remote_storage_refreshed', 'Remote storage refreshed.')
        );
    });
  }

  // Connect Cloud Remote button
  const addRemoteBtn = document.getElementById('btn-add-cloud-remote');
  if (addRemoteBtn) {
    addRemoteBtn.addEventListener('click', () => {
      const mount = document.getElementById('mgmt-storage-remotes-mount');
      openNewCloudRemoteModal(() => {
        if (mount) fetchAndRenderRemoteStorage(mount);
      });
    });
  }

  // Disks inventory refresh button
  const refreshDisksInvBtn = document.getElementById('btn-refresh-disks-inventory');

  if (refreshDisksInvBtn) {
    refreshDisksInvBtn.addEventListener('click', () => {
      fetchAndRenderDisksInventory();
      showToast(t('toast.disks_inventory_refreshed', 'Disks inventory refreshed.'), 'info');
    });
  }

  // Replication refresh and create pipeline buttons
  const refreshReplBtn = document.getElementById('btn-refresh-replication');
  if (refreshReplBtn) {
    refreshReplBtn.addEventListener('click', () => {
      fetchAndRenderReplication();
      showToast(t('toast.replication_pipelines_refreshed', 'Replication pipelines refreshed.'), 'info');
    });
  }

  const createReplBtn = document.getElementById('btn-create-replication-job');
  const replModal = document.getElementById('modal-create-replication-pipeline');
  if (createReplBtn && replModal) {
    const replCloseBtn = document.getElementById('modal-repl-close-btn');
    const replCancelBtn = document.getElementById('modal-repl-cancel-btn');
    const replForm = /** @type {HTMLFormElement} */ (document.getElementById('create-replication-pipeline-form'));
    const replTargetType = /** @type {HTMLSelectElement} */ (document.getElementById('repl-target-type'));
    const replRemoteFields = document.getElementById('repl-remote-fields');

    const closeReplModal = () => {
      replModal.classList.remove('open');
      replModal.style.display = 'none';
      if (replForm) replForm.reset();
      if (replRemoteFields) replRemoteFields.style.display = 'none';
    };

    if (replCloseBtn) replCloseBtn.onclick = closeReplModal;
    if (replCancelBtn) replCancelBtn.onclick = closeReplModal;

    if (replTargetType && replRemoteFields) {
      replTargetType.addEventListener('change', () => {
        replRemoteFields.style.display = replTargetType.value === 'local' ? 'none' : 'flex';
        if (replTargetType.value !== 'local') import('./replication-key.js').then((m) => m.showReplicationKey());
      });
    }

    const openReplModal = () => {
      replModal.style.removeProperty('display');
      replModal.style.display = 'flex';
      replModal.classList.add('open');
      bringToFront(replModal);
      const nameInput = document.getElementById('repl-job-name');
      if (nameInput) nameInput.focus();
    };

    createReplBtn.addEventListener('click', openReplModal);

    replModal.addEventListener('click', (e) => {
      if (e.target === replModal) closeReplModal();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && replModal.classList.contains('open')) {
        closeReplModal();
      }
    });

    if (replForm && !replForm._bound) {
      replForm._bound = true;
      replForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submitBtn = /** @type {HTMLButtonElement} */ (document.getElementById('btn-submit-repl-pipeline'));
        try {
          if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = t('ui.saving', 'Saving…');
          }
          const tType =
            /** @type {HTMLSelectElement} */ (document.getElementById('repl-target-type'))?.value || 'local';
          const payload = {
            name: /** @type {HTMLInputElement} */ (document.getElementById('repl-job-name'))?.value.trim(),
            source_pool: /** @type {HTMLInputElement} */ (document.getElementById('repl-source-pool'))?.value.trim(),
            source_dataset: /** @type {HTMLInputElement} */ (
              document.getElementById('repl-source-dataset')
            )?.value.trim(),
            target_type: tType,
            target_pool: /** @type {HTMLInputElement} */ (document.getElementById('repl-target-pool'))?.value.trim(),
            target_dataset: /** @type {HTMLInputElement} */ (
              document.getElementById('repl-target-dataset')
            )?.value.trim(),
            schedule: /** @type {HTMLSelectElement} */ (document.getElementById('repl-schedule'))?.value || 'daily',
            retention_count: parseInt(
              /** @type {HTMLInputElement} */ (document.getElementById('repl-retention'))?.value || '14',
              10
            ),
          };
          if (tType !== 'local') {
            payload.target_host =
              /** @type {HTMLInputElement} */ (document.getElementById('repl-target-host'))?.value.trim() || undefined;
            payload.target_port = parseInt(
              /** @type {HTMLInputElement} */ (document.getElementById('repl-target-port'))?.value || '22',
              10
            );
            payload.target_user =
              /** @type {HTMLInputElement} */ (document.getElementById('repl-target-user'))?.value.trim() || 'root';
          }
          await api.post('/api/storage/replication/jobs', payload);
          showToast(
            t('toast.replication_pipeline_created', "Replication pipeline '{name}' created.", { name: payload.name }),
            'success'
          );
          closeReplModal();
          fetchAndRenderReplication();
        } catch (err) {
          showToast(
            t('toast.failed_to_create_pipeline', 'Failed to create pipeline: {error}', { error: err.message }),
            'error'
          );
        } finally {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = t('ui.save_pipeline', 'Save Pipeline');
          }
        }
      });
    }
  }

  // the Tailscale details' Refresh is wired once, in network.js (C4: a second listener here read
  // everything twice and said "WireGuard", which is gone)

  // Check for updates and release channel toggles
  const checkUpdatesBtn = document.getElementById('btn-check-updates');
  if (checkUpdatesBtn) {
    checkUpdatesBtn.addEventListener('click', () => {
      fetchAndRenderSystemAbout(true);
    });
  }

  const btnChanStable = document.getElementById('btn-channel-stable');
  if (btnChanStable) {
    btnChanStable.addEventListener('click', () => {
      setUpdateChannel('stable');
    });
  }

  const btnChanEdge = document.getElementById('btn-channel-edge');
  if (btnChanEdge) {
    btnChanEdge.addEventListener('click', () => {
      setUpdateChannel('edge');
    });
  }

  const btnChanBeta = document.getElementById('btn-channel-beta');
  if (btnChanBeta) {
    btnChanBeta.addEventListener('click', () => {
      setUpdateChannel('beta');
    });
  }

  const applyUpdateBtn = document.getElementById('btn-apply-system-update');
  if (applyUpdateBtn) {
    applyUpdateBtn.addEventListener('click', applySystemUpdate);
  }
  const revertUpdateBtn = document.getElementById('btn-revert-system-update');
  if (revertUpdateBtn) {
    revertUpdateBtn.addEventListener('click', revertSystemUpdate);
  }

  // Diagnostics bundle buttons
  const downloadDiagBtn = document.getElementById('btn-download-diagnostics');
  if (downloadDiagBtn) {
    downloadDiagBtn.addEventListener('click', downloadDiagnosticsBundle);
  }
  const previewDiagBtn = document.getElementById('btn-preview-diagnostics');
  if (previewDiagBtn) {
    previewDiagBtn.addEventListener('click', previewDiagnosticsSummary);
  }
  const copySupportMdBtn = document.getElementById('btn-copy-support-md');
  if (copySupportMdBtn) {
    copySupportMdBtn.addEventListener('click', copySupportMarkdown);
  }
  const closeDiagPreviewBtn = document.getElementById('diagnostics-preview-close');
  if (closeDiagPreviewBtn) {
    closeDiagPreviewBtn.addEventListener('click', closeDiagnosticsPreviewModal);
  }
  const closeDiagPreviewFooterBtn = document.getElementById('btn-diag-preview-close');
  if (closeDiagPreviewFooterBtn) {
    closeDiagPreviewFooterBtn.addEventListener('click', closeDiagnosticsPreviewModal);
  }
  const copyDiagPreviewBtn = document.getElementById('btn-diag-preview-copy');
  if (copyDiagPreviewBtn) {
    copyDiagPreviewBtn.addEventListener('click', copySupportMarkdown);
  }
  const diagPreviewOverlay = document.getElementById('diagnostics-preview-modal-overlay');
  if (diagPreviewOverlay) {
    diagPreviewOverlay.addEventListener('click', (e) => {
      if (e.target === diagPreviewOverlay) {
        closeDiagnosticsPreviewModal();
      }
    });
    const diagWin = diagPreviewOverlay.querySelector('.smart-modal-window');
    const diagHeader = document.getElementById('diagnostics-preview-header');
    if (diagWin && diagHeader && typeof makeDraggable === 'function') {
      makeDraggable(diagWin, diagHeader, 'diagnostics-preview');
    }
  }

  // HTTPS Guidance Modal triggers
  const closeHttpsGuideBtn = document.getElementById('modal-https-guide-close');
  if (closeHttpsGuideBtn) {
    closeHttpsGuideBtn.addEventListener('click', closeHttpsGuideModal);
  }
  const closeHttpsGuideFooterBtn = document.getElementById('btn-modal-https-guide-close');
  if (closeHttpsGuideFooterBtn) {
    closeHttpsGuideFooterBtn.addEventListener('click', closeHttpsGuideModal);
  }
  const btnHttpsApps = document.getElementById('btn-https-guide-apps');
  if (btnHttpsApps) {
    btnHttpsApps.addEventListener('click', () => {
      closeHttpsGuideModal();
      window.openContainersManager?.({ view: 'catalog', search: 'reverse proxy' }); // the Apps window's catalog (SET-25)
    });
  }
  const btnHttpsPorts = document.getElementById('btn-https-guide-ports');
  if (btnHttpsPorts) {
    btnHttpsPorts.addEventListener('click', () => {
      closeHttpsGuideModal();
      window.openManagementWindow('mgmt-sec-network', 'mgmt-pane-network-ports');
    });
  }
  const btnCopyTailscale = document.getElementById('btn-copy-tailscale-serve');
  if (btnCopyTailscale) {
    btnCopyTailscale.addEventListener('click', async () => {
      const ok = await copyTextToClipboard('tailscale serve --https=443 127.0.0.1:8082');
      if (ok) showToast(t('common.copied', 'Copied to clipboard!'), 'success');
    });
  }
  const httpsGuideOverlay = document.getElementById('modal-https-guide-overlay');
  if (httpsGuideOverlay) {
    httpsGuideOverlay.addEventListener('click', (e) => {
      if (e.target === httpsGuideOverlay) {
        closeHttpsGuideModal();
      }
    });
    const httpsWin = httpsGuideOverlay.querySelector('.smart-modal-window');
    const httpsHeader = document.getElementById('modal-https-guide-header');
    if (httpsWin && httpsHeader && typeof makeDraggable === 'function') {
      makeDraggable(httpsWin, httpsHeader, 'https-guide');
    }
  }

  // 2FA Quick Action button
  const btnJump2fa = document.getElementById('btn-jump-to-2fa');
  if (btnJump2fa && !btnJump2fa.dataset.bound) {
    btnJump2fa.dataset.bound = 'true';
    btnJump2fa.addEventListener('click', () => {
      handleSecurityAdvisorClick('admin_mfa');
    });
  }

  // Notification Center triggers
  const sendTestAlertBtn = document.getElementById('btn-send-test-alert');
  if (sendTestAlertBtn) {
    sendTestAlertBtn.addEventListener('click', testAllNotificationChannels);
  }
  const saveNotifBtn = document.getElementById('btn-save-notifications'); // gone: the fields save themselves (SET-14)
  if (saveNotifBtn) {
    saveNotifBtn.addEventListener('click', () => saveNotificationsConfig());
  }
  document.querySelectorAll('.notif-cfg-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      openChannelConfigModal(btn.dataset.channel);
    });
  });
  document.querySelectorAll('.notif-test-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      testSingleChannel(btn.dataset.channel);
    });
  });
  const saveChannelModalBtn = document.getElementById('btn-save-channel-modal');
  if (saveChannelModalBtn) {
    saveChannelModalBtn.addEventListener('click', saveCurrentChannelModal);
  }
  const closeChannelModalBtn = document.getElementById('btn-close-channel-modal');
  if (closeChannelModalBtn) {
    closeChannelModalBtn.addEventListener('click', () => {
      const m = document.getElementById('modal-notification-channel');
      if (m) m.style.display = 'none';
    });
  }

  // Backup jobs & snapshots event bindings
  const btnOpenBackupJob = document.getElementById('btn-open-create-backup-job');
  const modalBackupJob = document.getElementById('modal-create-backup-job');
  const btnCloseBackupJob = document.getElementById('modal-backup-job-close-btn');
  const btnCancelBackupJob = document.getElementById('modal-backup-job-cancel-btn');
  const formBackupJob = /** @type {HTMLFormElement} */ (document.getElementById('create-backup-job-form'));
  const btnRefreshBackupJobs = document.getElementById('btn-refresh-backup-jobs');

  if (btnOpenBackupJob && modalBackupJob) {
    btnOpenBackupJob.addEventListener('click', () => {
      modalBackupJob.style.removeProperty('display');
      modalBackupJob.style.display = 'flex';
      modalBackupJob.classList.add('open');
      bringToFront(modalBackupJob);
      syncBackupJobForm(); // the fields that go with the chosen kind, from the first look
      const nameInput = document.getElementById('backup-job-name');
      if (nameInput) nameInput.focus();
    });
    modalBackupJob.addEventListener('click', (e) => {
      if (e.target === modalBackupJob) closeBackupModal();
    });
  }
  const closeBackupModal = () => {
    if (modalBackupJob) {
      modalBackupJob.classList.remove('open');
      modalBackupJob.style.display = 'none';
    }
  };
  if (btnCloseBackupJob) btnCloseBackupJob.addEventListener('click', closeBackupModal);
  if (btnCancelBackupJob) btnCancelBackupJob.addEventListener('click', closeBackupModal);

  const destTypeSelect = document.getElementById('backup-job-dest-type');
  const remoteFieldsDiv = document.getElementById('backup-remote-fields');
  if (destTypeSelect && remoteFieldsDiv) {
    destTypeSelect.addEventListener('change', () => syncBackupJobForm());
  }
  const kindSelect = document.getElementById('backup-job-kind');
  if (kindSelect) kindSelect.addEventListener('change', () => syncBackupJobForm());

  if (formBackupJob) {
    formBackupJob.addEventListener('submit', async (e) => {
      e.preventDefault();
      const kind = /** @type {HTMLSelectElement} */ (document.getElementById('backup-job-kind'))?.value || 'data';
      const payload = {
        name:
          /** @type {HTMLInputElement} */ (document.getElementById('backup-job-name'))?.value.trim() ||
          'Untitled Backup Task',
        kind,
        local_path:
          /** @type {HTMLInputElement} */ (document.getElementById('backup-job-local-path'))?.value.trim() || '',
        source_subvolume:
          kind === 'config'
            ? ''
            : /** @type {HTMLInputElement} */ (document.getElementById('backup-job-subvolume'))?.value.trim() || '',
        destination_type:
          /** @type {HTMLSelectElement} */ (document.getElementById('backup-job-dest-type'))?.value || 'local_snapshot',
        remote_name:
          /** @type {HTMLInputElement} */ (document.getElementById('backup-job-remote-name'))?.value.trim() || '',
        remote_path:
          /** @type {HTMLInputElement} */ (document.getElementById('backup-job-remote-path'))?.value.trim() || '',
        schedule: /** @type {HTMLSelectElement} */ (document.getElementById('backup-job-schedule'))?.value || 'daily',
        retention_count:
          parseInt(/** @type {HTMLInputElement} */ (document.getElementById('backup-job-retention'))?.value, 10) || 7,
        enabled: !!(/** @type {HTMLInputElement} */ (document.getElementById('backup-job-enabled'))?.checked),
      };
      const passphrase =
        /** @type {HTMLInputElement} */ (document.getElementById('backup-job-passphrase'))?.value || '';
      if (kind === 'config' && passphrase) payload.encryption_password = passphrase;

      try {
        await api.post('/api/backup/schedule', payload);
        showToast(t('toast.hyper_backup_pipeline_saved_successfully', 'Backup job saved.'), 'success');
        closeBackupModal();
        formBackupJob.reset();
        syncBackupJobForm();
        fetchAndRenderBackupJobs();
      } catch (err) {
        showToast(
          t('toast.failed_to_save_backup_job', 'Failed to save backup job: {error}', { error: err.message }),
          'error'
        );
      }
    });
  }

  if (btnRefreshBackupJobs) {
    btnRefreshBackupJobs.addEventListener('click', () => fetchAndRenderBackupJobs());
  }

  // Snapshots modal & actions
  const btnOpenSnapshot = document.getElementById('btn-open-create-snapshot');
  const modalSnapshot = document.getElementById('modal-create-snapshot');
  const btnCloseSnapshot = document.getElementById('modal-create-snapshot-close-btn');
  const btnCancelSnapshot = document.getElementById('modal-create-snapshot-cancel-btn');
  const formSnapshot = /** @type {HTMLFormElement} */ (document.getElementById('create-snapshot-form'));
  const btnRefreshSnapshots = document.getElementById('btn-refresh-snapshots');

  if (btnOpenSnapshot && modalSnapshot) {
    btnOpenSnapshot.addEventListener('click', () => {
      modalSnapshot.style.removeProperty('display');
      modalSnapshot.style.display = 'flex';
      modalSnapshot.classList.add('open');
      bringToFront(modalSnapshot);
      const subvolInput = document.getElementById('snapshot-subvol-input');
      if (subvolInput) subvolInput.focus();
    });
    modalSnapshot.addEventListener('click', (e) => {
      if (e.target === modalSnapshot) closeSnapshotModal();
    });
  }
  const closeSnapshotModal = () => {
    if (modalSnapshot) {
      modalSnapshot.classList.remove('open');
      modalSnapshot.style.display = 'none';
    }
  };
  if (btnCloseSnapshot) btnCloseSnapshot.addEventListener('click', closeSnapshotModal);
  if (btnCancelSnapshot) btnCancelSnapshot.addEventListener('click', closeSnapshotModal);

  if (formSnapshot) {
    formSnapshot.addEventListener('submit', async (e) => {
      e.preventDefault();
      const payload = {
        subvol_name:
          /** @type {HTMLInputElement} */ (document.getElementById('snapshot-subvol-input'))?.value.trim() || '',
        snapshot_name:
          /** @type {HTMLInputElement} */ (document.getElementById('snapshot-custom-name-input'))?.value.trim() ||
          undefined,
        readonly: !!(/** @type {HTMLInputElement} */ (document.getElementById('snapshot-readonly-input'))?.checked),
      };

      try {
        await api.post('/api/backup/snapshots', payload);
        showToast(
          t('toast.filesystem_snapshot_created_successfully', 'Filesystem snapshot created successfully!'),
          'success'
        );
        closeSnapshotModal();
        formSnapshot.reset();
        fetchAndRenderSystemSnapshots();
      } catch (err) {
        showToast(
          t('toast.failed_to_create_snapshot', 'Failed to create snapshot: {error}', { error: err.message }),
          'error'
        );
      }
    });
  }

  if (btnRefreshSnapshots) {
    btnRefreshSnapshots.addEventListener('click', () => fetchAndRenderSystemSnapshots());
  }

  // Application Backups event bindings
  const btnRefreshAppBackups = document.getElementById('btn-refresh-app-backups');
  if (btnRefreshAppBackups) {
    btnRefreshAppBackups.addEventListener('click', () => {
      const filterApp =
        /** @type {HTMLSelectElement} */ (document.getElementById('app-backups-filter-app'))?.value || '';
      fetchAndRenderAppBackups(null, filterApp);
      showToast(t('toast.application_backups_refreshed', 'Application backups refreshed.'), 'info');
    });
  }

  const selectFilterAppBackups = /** @type {HTMLSelectElement} */ (document.getElementById('app-backups-filter-app'));
  if (selectFilterAppBackups) {
    selectFilterAppBackups.addEventListener('change', () => {
      fetchAndRenderAppBackups(null, selectFilterAppBackups.value);
    });
  }

  // Language switch update
  window.addEventListener('kiboto:lang-changed', () => {
    const activeSection = Array.from(document.querySelectorAll('.mgmt-detail-card')).find(
      (c) => c.style.display !== 'none'
    );
    if (activeSection) {
      showSection(activeSection.id);
    } else if (hubView && hubView.style.display !== 'none') {
      showHub();
    }
  });

  // VM changes listener
  window.addEventListener('vm-updated', () => {
    fetchAndRenderMgmtVms();
  });

  // Kib Multi-Modal RAG & Visual Search Engine
  initAiKnowledgeEngine();
  if (typeof restoreHardwareTabsToManagement === 'function') restoreHardwareTabsToManagement();
}
