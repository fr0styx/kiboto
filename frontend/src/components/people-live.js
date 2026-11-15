// The People lists update themselves (SET-19): the server sends security.people_rev with the live stats and
// raises it whenever people or their sign-ins change; while People is open, the lists reload when it
// moves, a moment later so several changes make one reload.
const SETTLE_MS = 600;

/** Listens on the bus; reload() runs when the count moves while shown() is true. */
export function installPeopleLive({ bus, reload, shown, settleMs = SETTLE_MS }) {
  let seen = null;
  let timer = null;
  const onStats = (stats) => {
    const rev = stats?.security?.people_rev;
    if (typeof rev !== 'number') return;
    const moved = seen !== null && rev !== seen;
    seen = rev;
    if (!moved || !shown()) return;
    clearTimeout(timer);
    timer = setTimeout(reload, settleMs);
  };
  bus.on('stats:updated', onStats);
  return onStats;
}

/** Whether People is on screen: its pane shown inside an open Settings window. */
export function peopleShown(doc = document) {
  const pane = doc.getElementById('mgmt-pane-users');
  const overlay = doc.getElementById('management-modal-overlay');
  return Boolean(pane && overlay && pane.style.display !== 'none' && overlay.style.display !== 'none');
}
