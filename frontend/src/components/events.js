/**
 * Activity -> History (SET-27, Activity report section 4): what happened, by day. One view of an
 * entry for the history, the bell and the dialog (event-view.js); chips and a search filter it;
 * each entry opens the page that deals with it, and its technical details fold open in place.
 */
import { eventView, eventWhen, eventPlace, needsALook } from '../event-view.js';
import { api } from '../api.js';
import { escapeHtml, copyTextToClipboard } from '../utils.js';
import { t, getLanguage } from '../i18n.js';
import { formatDate, formatTime } from '../format.js';
import { emptyStateHtml } from './empty-state.js';
import { state } from '../state.js';

let _lastEventHash = '';
const _expandedEvents = new Set();
let _currentFilter = 'all';
let _query = '';
let _events = [];

/** "Today", "Yesterday" or the date, in the reader's language. */
export function dayLabel(ts, now = new Date()) {
  const d = new Date(ts * 1000);
  const start = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((start(now) - start(d)) / 86400000);
  if (days === 0) return t('act.today', 'Today');
  if (days === 1) return t('act.yesterday', 'Yesterday');
  return formatDate(d);
}

// The "seen up to" mark the bell keeps (dock/notifications.js), read here without importing it: a
// lazy module that imports small first-load helpers makes the build split them into first-load
// chunks of their own, over the first-load budget (it did, 16 Nov 2026)
const SEEN_COPY = 'kiboto_last_read_event_ts_v2'; // gitleaks:allow (a storage key name)

export function seenUpTo(user = /** @type {any} */ (globalThis).kibotoUser) {
  let local = 0;
  try {
    local = parseFloat(localStorage.getItem(SEEN_COPY) || '0') || 0;
  } catch {
    /* private window */
  }
  const prefs = (user && (user.preferences || user.user?.preferences)) || {};
  return Math.max(local, Number(prefs.events_seen) || 0);
}

/** Everything up to the newest entry is seen, here and in the bell (saved with the account). */
export function markSeen(events) {
  const newest = Math.max(0, ...(events || []).map(eventWhen));
  if (!newest) return 0;
  try {
    localStorage.setItem(SEEN_COPY, String(newest));
  } catch {
    /* private window */
  }
  api.put('/api/auth/me/preferences', { events_seen: newest }).catch(() => {});
  return newest;
}

/** The problems not seen yet: red (failed or critical) and newer than the seen mark. */
export function pinnedEvents(events, isRead = (e) => eventWhen(e) <= seenUpTo()) {
  return (events || []).filter((e) => eventView(e).look === 'error' && !isRead(e));
}

/** The entries the chips and the search leave. */
export function filterEvents(events, filter = 'all', query = '') {
  const q = (query || '').trim().toLowerCase();
  return (events || []).filter((e) => {
    if (filter === 'look' && !needsALook(e)) return false;
    if (!q) return true;
    const v = eventView(e);
    return `${v.title} ${v.message}`.toLowerCase().includes(q);
  });
}

function ensureControls(list) {
  if (list.previousElementSibling && list.previousElementSibling.classList.contains('history-controls')) return;
  const bar = document.createElement('div');
  bar.className = 'history-controls';
  bar.innerHTML = `
    <div class="history-chips" role="group" aria-label="${escapeHtml(t('act.filter', 'Show'))}" data-i18n-aria-label="act.filter">
      <button type="button" class="btn-pill-toggle history-chip active" data-filter="all" aria-pressed="true">${escapeHtml(t('act.chip_all', 'All'))}</button>
      <button type="button" class="btn-pill-toggle history-chip" data-filter="look" aria-pressed="false">${escapeHtml(t('act.chip_look', 'Needs a look'))}</button>
      <button type="button" class="btn-pill-toggle history-chip" data-filter="files" aria-pressed="false" hidden>${escapeHtml(t('act.chip_files', 'Files'))}</button>
      <button type="button" class="btn-pill-toggle history-chip" data-filter="signins" aria-pressed="false" hidden>${escapeHtml(t('act.chip_signins', 'Sign-ins'))}</button>
    </div>
    <input type="search" class="tz-text-input history-search" placeholder="${escapeHtml(t('act.search', 'Search the history'))}" aria-label="${escapeHtml(t('act.search', 'Search the history'))}" data-i18n-aria-label="act.search">
    <button type="button" class="btn-pill-toggle is-small history-export">${escapeHtml(t('act.export', 'Save as a file'))}</button>`;
  list.before(bar);
  // Sign-ins for people who may read the security log (Activity report section 4, row 5)
  import('./history-signins.js')
    .then((m) => {
      // Files and Sign-ins share the audit right (File activity, the security log)
      bar.querySelectorAll('[data-filter="signins"], [data-filter="files"]').forEach((chip) => {
        /** @type {HTMLElement} */ (chip).hidden = !m.maySeeSignins();
      });
    })
    .catch(() => {});
  bar.addEventListener('click', (ev) => {
    const chip = /** @type {HTMLElement | null} */ (/** @type {Element} */ (ev.target).closest('.history-chip'));
    if (!chip) return;
    _currentFilter = chip.dataset.filter || 'all';
    bar.querySelectorAll('.history-chip').forEach((c) => {
      const on = c === chip;
      c.classList.toggle('active', on);
      c.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    redraw();
  });
  bar.querySelector('.history-export')?.addEventListener('click', () => {
    import('./history-export.js')
      .then((m) =>
        m.exportHistory({
          filter: _currentFilter,
          events: filterEvents(_events, _currentFilter, _query),
          view: eventView,
        })
      )
      .catch(() => {});
  });
  bar.querySelector('.history-search')?.addEventListener('input', (ev) => {
    _query = /** @type {HTMLInputElement} */ (ev.target).value;
    redraw();
  });
}

function redraw() {
  _lastEventHash = '';
  const save = /** @type {HTMLElement | null} */ (document.querySelector('.history-export'));
  if (save) save.hidden = _currentFilter === 'files'; // file activity has no file to save yet
  if (_currentFilter === 'signins' || _currentFilter === 'files') {
    const list = document.getElementById('events-list');
    const search = /** @type {HTMLElement | null} */ (document.querySelector('.history-search'));
    if (search) search.hidden = true; // each has its own search
    if (list && _currentFilter === 'signins')
      import('./history-signins.js').then((m) => m.renderSignins(list)).catch(() => {});
    if (list && _currentFilter === 'files')
      import('./file-activity.js').then((m) => m.renderFileActivity(list)).catch(() => {});
    return;
  }
  const search = /** @type {HTMLElement | null} */ (document.querySelector('.history-search'));
  if (search) search.hidden = false;
  renderEventLog(_events);
}

function entryRow(e) {
  const v = eventView(e); // one view for the history, the bell and the dialog (SET-13)
  const place = eventPlace(e);
  const key = `${e.id || e.ts}_${e.title}`;
  const row = document.createElement('article');
  row.className = `history-entry is-${v.look}`;
  const time = [formatTime(new Date(v.when * 1000)), v.repeated].filter(Boolean).join(' · ');
  row.innerHTML = `
    <div class="history-line">
      <span class="history-icon" aria-hidden="true">${escapeHtml(v.icon)}</span>
      <div class="history-text">
        <div class="history-title" style="color: ${escapeHtml(v.color)};">${escapeHtml(v.title)} <span class="history-word">${escapeHtml(v.word)}</span></div>
        <div class="history-message">${escapeHtml(v.message)}</div>
        <div class="history-time">${escapeHtml(time)}</div>
      </div>
      <div class="history-actions">
        ${place.route !== 'events' ? `<button type="button" class="btn-pill-toggle history-open">${escapeHtml(t('act.open', 'Open'))}</button>` : ''}
        <button type="button" class="btn-pill-toggle history-more" aria-expanded="false">${escapeHtml(t('act.tech', 'Technical details'))}</button>
      </div>
    </div>
    <div class="history-details" hidden>
      <pre></pre>
      <button type="button" class="btn-pill-toggle history-copy">${escapeHtml(t('act.copy', 'Copy'))}</button>
    </div>`;
  const details = /** @type {HTMLElement} */ (row.querySelector('.history-details'));
  /** @type {HTMLElement} */ (row.querySelector('pre')).textContent = JSON.stringify(e, null, 2);
  const more = /** @type {HTMLElement} */ (row.querySelector('.history-more'));
  const setOpen = (open) => {
    details.hidden = !open;
    more.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) _expandedEvents.add(key);
    else _expandedEvents.delete(key);
  };
  setOpen(_expandedEvents.has(key));
  more.addEventListener('click', () => setOpen(details.hidden));
  row.querySelector('.history-open')?.addEventListener('click', () => place.open());
  row.querySelector('.history-copy')?.addEventListener('click', () => copyTextToClipboard(JSON.stringify(e, null, 2)));
  return row;
}

export function renderEventLog(events) {
  const list = document.getElementById('events-list');
  if (!list) return;
  _events = events || [];
  ensureControls(list);
  if (_currentFilter === 'signins' || _currentFilter === 'files') return; // their own lists are on screen; new events wait for All

  // a counted repeat changes neither the length nor the first time: the hash carries both, and the language
  const top = _events[0];
  const currentHash = `${_events.length}-${top ? `${top.id}-${eventWhen(top)}-${top.count || 1}` : 0}-${_currentFilter}-${_query}-${getLanguage()}`;
  if (_lastEventHash === currentHash) return;
  _lastEventHash = currentHash;

  if (_events.length === 0) {
    list.innerHTML = emptyStateHtml({
      compact: true,
      title: t('events.none_title', 'Nothing has happened yet'),
      body: t('events.none_desc', 'Alerts, backups, power, app and hardware events appear here as they happen.'),
    });
    return;
  }
  const shown = filterEvents(_events, _currentFilter, _query);
  if (shown.length === 0) {
    list.innerHTML = `<div class="history-none">${escapeHtml(t('act.none_match', 'Nothing in the history matches.'))}</div>`;
    return;
  }
  list.replaceChildren();
  // problems not seen yet stay on top until read (Activity report section 4, row 1)
  const pinned = _currentFilter === 'all' && !_query ? pinnedEvents(_events) : [];
  if (pinned.length) {
    const box = document.createElement('section');
    box.className = 'history-pinned';
    const head = document.createElement('div');
    head.className = 'history-pinned-head';
    const h = document.createElement('h3');
    h.className = 'history-day';
    h.textContent = t('act.pinned', 'Not seen yet');
    const seen = document.createElement('button');
    seen.type = 'button';
    seen.className = 'btn-pill-toggle history-seen';
    seen.textContent = t('act.mark_seen', 'Mark as seen');
    seen.addEventListener('click', () => {
      markSeen(_events);
      redraw();
    });
    head.append(h, seen);
    box.append(head, ...pinned.map((e) => entryRow(e)));
    list.append(box);
  }
  let day = '';
  for (const e of shown) {
    const label = dayLabel(eventWhen(e));
    if (label !== day) {
      day = label;
      const h = document.createElement('h3');
      h.className = 'history-day';
      h.textContent = label;
      list.append(h);
    }
    list.append(entryRow(e));
  }
}

export function initEvents() {
  // The stats stream sends the events only when they change, usually before this list existed:
  // draw the ones the page already has
  _lastEventHash = '';
  if (state.latestStats?.events) renderEventLog(state.latestStats.events);
  // "Clear Event Log" is gone (SET-13): it deleted for everyone, with no undo and no record of
  // who did it. Entries leave by themselves after 90 days.
  window.addEventListener('kiboto:lang-changed', () => {
    if (state.latestStats?.events) renderEventLog(state.latestStats.events); // the open log kept the old language
  });
}
