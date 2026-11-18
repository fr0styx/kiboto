// The Kib window (SET-26, AI 5; owner's decision 1): Ask and Search are an app of their own, for
// every role that may use Kib; Settings → Kib holds only the settings. The two panes keep their
// markup and code: the window takes them out of Settings the first time it opens, so every handler
// the page code bound stays bound.
import { ensureManagementDom } from '../management-dom.js';
import { api } from '../api.js';
import { makeDraggable, bringToFront } from './dock.js';
import { ZettEventBus } from '../event-bus.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import '../styles/kib-window.css'; // the window's own sheet loads with this code

export const KIB_PANES = ['mgmt-pane-ai-chat', 'mgmt-pane-ai-rag'];
const WIN_ID = 'kib-window';

/** The pane a link asks for, as the window shows it: photo search is part of Search. */
export function kibPane(pane) {
  if (pane === 'mgmt-pane-ai-visual' || pane === 'mgmt-pane-ai-rag') return 'mgmt-pane-ai-rag';
  return 'mgmt-pane-ai-chat';
}

/** True for a Settings link that now belongs to the Kib window. */
export function isKibWindowPane(pane) {
  return pane === 'mgmt-pane-ai-chat' || pane === 'mgmt-pane-ai-rag' || pane === 'mgmt-pane-ai-visual';
}

function hide(win, how) {
  win.classList.add('window-minimized');
  win.classList.remove('open');
  win.style.setProperty('display', 'none', 'important');
  const dm = /** @type {any} */ (window).DockManager;
  if (dm) (how === 'close' ? dm.closeWindow : dm.minimize).call(dm, 'kib');
}

/** Puts the window in the page once, with its two tabs and buttons. */
export function ensureKibWindow() {
  let win = document.getElementById(WIN_ID);
  if (win) return win;
  const tabHtml = (
    pane,
    icon,
    words
  ) => `<button type="button" class="mgmt-inner-tab" role="tab" aria-selected="false" data-kib-tab="${pane}">
      <svg class="ic" style="width:14px;height:14px" aria-hidden="true"><use href="${icon}"/></svg><span>${escapeHtml(words)}</span></button>`;
  document.body.insertAdjacentHTML(
    'beforeend',
    `
    <div id="kib-window" class="os-window kib-window" role="dialog" aria-labelledby="kib-window-title" style="display:none">
      <div class="os-window-header">
        <div class="os-window-title"><svg class="ic" style="width:14px;height:14px" aria-hidden="true"><use href="#i-kib"/></svg><span id="kib-window-title">${escapeHtml(t('kibw.title', 'Kib'))}</span></div>
        <div class="os-window-controls">
          <button class="win-btn min-btn" data-kibw="min" title="${escapeHtml(t('window.minimize', 'Minimize'))}" data-i18n-title="window.minimize" aria-label="${escapeHtml(t('window.minimize', 'Minimize'))}" data-i18n-aria-label="window.minimize"></button>
          <button class="win-btn max-btn" data-kibw="max" title="${escapeHtml(t('ui.maximize', 'Maximize'))}" data-i18n-title="ui.maximize" aria-label="${escapeHtml(t('ui.maximize', 'Maximize'))}" data-i18n-aria-label="ui.maximize"></button>
          <button class="win-btn close-btn" data-kibw="close" title="${escapeHtml(t('diagnostics.close_btn', 'Close'))}" data-i18n-title="diagnostics.close_btn" aria-label="${escapeHtml(t('diagnostics.close_btn', 'Close'))}" data-i18n-aria-label="diagnostics.close_btn"></button>
        </div>
      </div>
      <div class="mgmt-inner-tabs kib-window-tabs" role="tablist">
        ${tabHtml('mgmt-pane-ai-chat', '#i-kib', t('ai.tab_chat', 'Ask Kib'))}
        ${tabHtml('mgmt-pane-ai-rag', '#i-search', t('ai.tab_rag', 'AI search'))}
      </div>
      <div class="kib-window-body"></div>
    </div>`
  );
  win = /** @type {HTMLElement} */ (document.getElementById(WIN_ID));
  win.querySelector('[data-kibw="min"]')?.addEventListener('click', () => hide(win, 'min'));
  win.querySelector('[data-kibw="close"]')?.addEventListener('click', () => hide(win, 'close'));
  win.querySelector('[data-kibw="max"]')?.addEventListener('click', () => win.classList.toggle('is-maximized'));
  win
    .querySelectorAll('[data-kib-tab]')
    .forEach((b) =>
      b.addEventListener('click', () => showKibPane(/** @type {HTMLElement} */ (b).dataset.kibTab || ''))
    );
  makeDraggable(win, win.querySelector('.os-window-header'));
  win.addEventListener('mousedown', () => bringToFront(win));
  return win;
}

/** Takes Ask and Search out of Settings into the window (once); Settings keeps the settings. */
export function adoptPanes(win) {
  const body = win.querySelector('.kib-window-body');
  if (!body) return;
  for (const id of KIB_PANES) {
    const pane = document.getElementById(id);
    if (pane && pane.parentElement !== body) body.appendChild(pane);
    document.getElementById(id.replace('mgmt-pane-', 'mgmt-tab-'))?.setAttribute('hidden', '');
  }
}

/**
 * Says "Kib is turned off for you" before anyone types (AI 5): Who can use Kib may switch asking
 * or searching off for a role. The box and button of a switched-off pane are disabled.
 * @param {{ allowed?: boolean, search?: boolean } | null} me GET /api/ai/access/me
 */
export function markKibAccess(me) {
  const parts = [
    ['mgmt-pane-ai-chat', me?.allowed !== false, ['ai-chat-input', 'btn-ai-chat-send']],
    ['mgmt-pane-ai-rag', me?.search !== false, ['ai-visual-search-input', 'btn-ai-rag-ask']],
  ];
  for (const [paneId, on, controls] of parts) {
    const pane = document.getElementById(/** @type {string} */ (paneId));
    if (!pane) continue;
    let note = pane.querySelector(':scope > .kib-off-note');
    if (!on && !note) {
      note = document.createElement('p');
      note.className = 'kib-off-note';
      note.setAttribute('role', 'status');
      note.textContent = t(
        'kibw.off_for_you',
        'Kib is turned off for you. The person who runs this NAS can turn it on under Settings → Kib → Who can use Kib.'
      );
      pane.prepend(note);
    }
    if (on && note) note.remove();
    for (const id of /** @type {string[]} */ (controls)) {
      const el = /** @type {HTMLInputElement | null} */ (document.getElementById(id));
      if (el) el.disabled = !on;
    }
  }
}

/** Shows one pane and marks its tab. */
export function showKibPane(pane) {
  for (const id of KIB_PANES) {
    const el = document.getElementById(id);
    if (el) el.style.display = id === pane ? (id === 'mgmt-pane-ai-chat' ? 'flex' : 'block') : 'none';
  }
  document.querySelectorAll('#kib-window [data-kib-tab]').forEach((b) => {
    const on = /** @type {HTMLElement} */ (b).dataset.kibTab === pane;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  import('./management/ai.js')
    .then((ai) => {
      ai.fetchAndRenderAiStatus();
      import('./management/kib-access.js').then((m) => m.loadKibExtras(pane)).catch(() => {}); // each person's Immich with Search
      if (pane === 'mgmt-pane-ai-chat') document.getElementById('ai-chat-input')?.focus();
      else ai.runAiVisualSearch(ai._getActiveAiSearchQuery() || null);
    })
    .catch(() => {});
}

/**
 * Opens the Kib window on Ask or Search. Settings' markup is loaded first if it is not yet, since
 * the panes live there until the window takes them.
 * @param {string} [pane]
 */
export async function openKibWindow(pane = 'mgmt-pane-ai-chat') {
  await ensureManagementDom();
  const win = ensureKibWindow();
  adoptPanes(win);
  const dm = /** @type {any} */ (window).DockManager;
  if (dm) {
    if (!dm.windows?.kib) dm.register('kib', win, '#i-kib', t('kibw.title', 'Kib'));
    dm.restore('kib');
  }
  win.classList.remove('window-minimized');
  win.classList.add('open');
  win.style.removeProperty('display');
  win.style.display = 'flex';
  bringToFront(win);
  showKibPane(kibPane(pane));
  api
    .get('/api/ai/access/me')
    .then(markKibAccess)
    .catch(() => {}); // unknown: leave it as it is
  ZettEventBus.emit('window:open', { id: WIN_ID });
  return win;
}
