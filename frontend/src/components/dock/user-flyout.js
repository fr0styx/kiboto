// The profile menu that opens from the top bar's user pill.
// Part of dock.js, split out by ARC-5; loaded on the first click (user-pill.js), not at start.

import { KibotoEventBus } from '../../event-bus.js';
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';

export function toggleUserProfileFlyout(anchorEl) {
  let flyout = document.getElementById('user-profile-flyout');
  if (!flyout) {
    flyout = document.createElement('div');
    flyout.id = 'user-profile-flyout';
    flyout.className = 'user-profile-flyout glassmorphic-panel';
    flyout.innerHTML = `
      <div class="user-flyout-header ufl-head">
        <div id="user-flyout-avatar" class="ufl-avatar">
          A
        </div>
        <div class="ufl-text">
          <div id="user-flyout-name" class="ufl-name">${escapeHtml(t('dock.uf_admin', 'Administrator'))}</div>
          <div id="user-flyout-username" class="ufl-user">@admin</div>
          <span id="user-flyout-role" class="ufl-role">${escapeHtml(t('role.superadmin', 'Administrator'))}</span>
        </div>
      </div>
      <div class="user-flyout-actions ufl-actions">
        <button class="user-flyout-btn ufl-btn" id="btn-flyout-lock">
          <span class="ufl-ico">🔒</span> <span>${escapeHtml(t('dock.uf_lock', 'Lock screen'))}</span>
          <span class="ufl-key">Cmd+L</span>
        </button>
        <button class="user-flyout-btn ufl-btn" id="btn-flyout-users">
          <span class="ufl-ico">👥</span> <span>${escapeHtml(t('dock.uf_people', 'People and permissions'))}</span>
        </button>
        <button class="user-flyout-btn ufl-btn" id="btn-flyout-security">
          <span class="ufl-ico">🛡️</span> <span>${escapeHtml(t('account.title', 'My account'))}</span>
        </button>
        <button class="user-flyout-btn ufl-btn" id="btn-flyout-power" hidden>
          <span class="ufl-ico">⏻</span> <span>${escapeHtml(t('pws.title', 'Restart or shut down'))}</span>
        </button>
        <div class="ufl-sep"></div>
        <button class="user-flyout-btn ufl-btn-soft" id="btn-flyout-switch">
          <span class="ufl-ico">🔄</span> <span>${escapeHtml(t('dock.uf_switch', 'Switch person'))}</span>
        </button>
        <button class="user-flyout-btn ufl-btn-crit" id="btn-flyout-logout">
          <span class="ufl-ico">🚪</span> <span>${escapeHtml(t('mgmt.sec_logout', 'Sign out'))}</span>
        </button>
      </div>
    `;
    document.body.appendChild(flyout);

    // Hover effect for buttons
    flyout.querySelectorAll('.user-flyout-btn').forEach((btn) => {
      btn.addEventListener('mouseenter', () => {
        btn.style.background = 'rgba(255,255,255,0.08)';
      });
      btn.addEventListener('mouseleave', () => {
        btn.style.background = 'transparent';
      });
    });

    const resetFlyoutTrigger = () => {
      if (anchorEl) {
        anchorEl.setAttribute('aria-expanded', 'false');
        anchorEl.classList.remove('active');
      }
      const topbarPill = document.getElementById('topbar-user-pill');
      if (topbarPill) {
        topbarPill.setAttribute('aria-expanded', 'false');
        topbarPill.classList.remove('active');
      }
    };

    // Actions
    document.getElementById('btn-flyout-lock').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      import('../auth.js').then((m) => m.lockDesktop());
    });

    const openMgmtPane = (pane, subtab = null) => {
      if (typeof window.openManagementWindow === 'function') {
        window.openManagementWindow(pane, null, subtab);
      } else {
        import('../management.js')
          .then((m) => {
            if (typeof m.initManagement === 'function') m.initManagement();
            if (typeof window.openManagementWindow === 'function') {
              window.openManagementWindow(pane, null, subtab);
            } else {
              document.getElementById('management-desktop-icon')?.click();
            }
          })
          .catch(() => {
            document.getElementById('management-desktop-icon')?.click();
          });
      }
      KibotoEventBus.emit('window:open', { id: 'management', pane: pane, subtab: subtab });
    };

    document.getElementById('btn-flyout-users').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      openMgmtPane('mgmt-pane-users', 'users-pane-list');
    });

    document.getElementById('btn-flyout-security').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      openMgmtPane('mgmt-pane-account');
    });

    // Restart or shut down (SET-31, X5 d): for people who may switch the NAS; it opens Power there
    const powerBtn = /** @type {HTMLElement} */ (document.getElementById('btn-flyout-power'));
    import('../../route-access.js')
      .then((m) => {
        powerBtn.hidden = !m.hasScope(m.currentUser()?.scopes || [], 'system:power');
      })
      .catch(() => {});
    powerBtn.addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      openMgmtPane('mgmt-sec-ups');
      setTimeout(() => document.getElementById('power-switch')?.scrollIntoView?.({ block: 'center' }), 900);
    });

    document.getElementById('btn-flyout-switch').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      import('../auth.js').then((m) => m.switchUser());
    });

    document.getElementById('btn-flyout-logout').addEventListener('click', () => {
      flyout.style.display = 'none';
      resetFlyoutTrigger();
      import('../auth.js').then((m) => m.logout());
    });

    // Click outside to close
    document.addEventListener('click', (evt) => {
      if (flyout.style.display !== 'none' && !flyout.contains(/** @type {Node} */ (evt.target))) {
        const topbarPill = document.getElementById('topbar-user-pill');
        if (
          (!anchorEl || !anchorEl.contains(/** @type {Node} */ (evt.target))) &&
          (!topbarPill || !topbarPill.contains(/** @type {Node} */ (evt.target)))
        ) {
          flyout.style.display = 'none';
          resetFlyoutTrigger();
        }
      }
    });

    document.addEventListener('keydown', (evt) => {
      if (evt.key === 'Escape' && flyout.style.display === 'block') {
        flyout.style.display = 'none';
        resetFlyoutTrigger();
      }
    });
  }

  // Toggle display
  if (flyout.style.display === 'block') {
    flyout.style.display = 'none';
    if (anchorEl) {
      anchorEl.setAttribute('aria-expanded', 'false');
      anchorEl.classList.remove('active');
    }
    const topbarPill = document.getElementById('topbar-user-pill');
    if (topbarPill) {
      topbarPill.setAttribute('aria-expanded', 'false');
      topbarPill.classList.remove('active');
    }
    return;
  }

  // Refresh current user info
  import('../session.js').then((m) => m.updateUserInterfaceElements());

  const rect = anchorEl ? anchorEl.getBoundingClientRect() : { top: 0, bottom: 48, left: 16, width: 30 };
  const flyoutW = 250;
  const isTopBar = rect.top < (typeof window !== 'undefined' ? window.innerHeight / 2 : 400);

  if (isTopBar) {
    const topPos = rect.bottom + 8;
    const leftPos = Math.max(
      12,
      Math.min((typeof window !== 'undefined' ? window.innerWidth : 1200) - flyoutW - 12, rect.left)
    );
    flyout.style.position = 'fixed';
    flyout.style.top = `${topPos}px`;
    flyout.style.bottom = 'auto';
    flyout.style.left = `${leftPos}px`;
    flyout.style.animation = 'flyoutSlideDown 0.18s cubic-bezier(0.16, 1, 0.3, 1)';
  } else {
    const bottomPos = (typeof window !== 'undefined' ? window.innerHeight : 900) - rect.top + 12;
    const leftPos = Math.max(
      16,
      Math.min(
        (typeof window !== 'undefined' ? window.innerWidth : 1200) - flyoutW - 16,
        rect.left + rect.width / 2 - flyoutW / 2
      )
    );
    flyout.style.position = 'fixed';
    flyout.style.top = 'auto';
    flyout.style.bottom = `${bottomPos}px`;
    flyout.style.left = `${leftPos}px`;
    flyout.style.animation = 'flyoutSlideUp 0.18s cubic-bezier(0.16, 1, 0.3, 1)';
  }

  flyout.style.width = `${flyoutW}px`;
  flyout.style.zIndex = '99999';
  flyout.style.display = 'block';

  if (anchorEl) {
    anchorEl.setAttribute('aria-expanded', 'true');
    anchorEl.classList.add('active');
  }
}
