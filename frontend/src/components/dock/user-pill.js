// The top bar's user pill. The menu it opens (user-flyout.js) loads on the first click,
// so it stays out of the first load.

/** @param {HTMLElement} pill */
function openMenu(pill) {
  import('./user-flyout.js').then((m) => m.toggleUserProfileFlyout(pill)).catch(() => {});
}

export function initTopbarUserPill() {
  const topbarPill = document.getElementById('topbar-user-pill');
  if (!topbarPill || topbarPill.dataset.userPillBound === 'true') return;
  topbarPill.dataset.userPillBound = 'true';

  topbarPill.addEventListener('click', (e) => {
    e.stopPropagation();
    openMenu(topbarPill);
  });

  topbarPill.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      e.stopPropagation();
      openMenu(topbarPill);
    }
  });
}

/** Opens or closes the profile menu next to `anchorEl` (loads it first when needed).
 * @param {HTMLElement} anchorEl */
export async function toggleUserProfileFlyout(anchorEl) {
  const m = await import('./user-flyout.js');
  m.toggleUserProfileFlyout(anchorEl);
}
