// Apps window: "For the family" (SET-19 stage 5, Users decision 10). The household set-ups that are
// built on an app from the catalog live here: the device filter (AdGuard Home), the calendar and
// contacts (the office suite) and one sign-in for the apps (Pocket ID). People shows one link row
// each, with its state, that opens this group.
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';

const card = (id, title, desc, mount) =>
  `<section class="apps-family-card" aria-labelledby="${id}"><h4 id="${id}" class="invite-title">${escapeHtml(title)}</h4>${desc ? `<p class="invite-meta">${escapeHtml(desc)}</p>` : ''}<div id="${mount}"></div></section>`;

/** The folded group, closed: nothing is read until someone opens it. */
export function appsFamilyHtml() {
  return `<details class="apps-experts" id="apps-family">
    <summary>${escapeHtml(t('apps.family', 'For the family'))}</summary>
    <p class="apps-experts-desc">${escapeHtml(t('apps.family_desc', 'Set-ups for the household, each built on an app from the catalog.'))}</p>
    ${card('ff-title', t('ff.title', "Filter the kids' devices"), t('ff.desc', "With AdGuard Home from the App Catalog answering your network's DNS, a family account's phones and tablets get parental control, safe search and safe browsing, and the services you pick are blocked. Everyone else is unchanged."), 'family-filter-mount')}
    ${card('fc-title', t('fc.title', 'Family calendar and contacts'), t('fc.desc', "A shared calendar and address book kept at home, which everyone's phone syncs. It lives in the office suite from the App Catalog."), 'family-calendar-mount')}
    ${card('fs-title', t('fs.title', "One sign-in for the family's apps"), '', 'family-signin-mount')}
  </details>`;
}

/** Fills the three cards (each module and its sheet load only now). @param {ParentNode} [root] */
export function renderFamilyCards(root = document) {
  const mount = (id) => root.querySelector(`#${id}`);
  // @ts-expect-error a style sheet has no types; Vite loads it with the cards
  import('../styles/users-lazy.css').catch(() => {});
  if (mount('family-filter-mount')) import('./family-filter.js').then((m) => m.renderFamilyFilter(mount('family-filter-mount'))).catch(() => {});
  if (mount('family-calendar-mount')) import('./family-calendar.js').then((m) => m.renderFamilyCalendar(mount('family-calendar-mount'))).catch(() => {});
  if (mount('family-signin-mount')) import('./family-signin.js').then((m) => m.renderFamilySignin(mount('family-signin-mount'))).catch(() => {});
}

/** Reads the cards each time the group opens. Bound once. @param {ParentNode} [root] */
export function installAppsFamily(root = document) {
  const group = /** @type {HTMLDetailsElement | null} */ (root.querySelector('#apps-family'));
  if (!group || group.dataset.bound) return false;
  group.dataset.bound = '1';
  group.addEventListener('toggle', () => {
    if (group.open) renderFamilyCards(group);
  });
  return true;
}

export const PARTS = { filter: 'ff-title', calendar: 'fc-title', signin: 'fs-title' };

/** Opens the group (from People's link rows) and brings the named card into view. */
export function openFamily(root = document, part = '') {
  const group = /** @type {HTMLDetailsElement | null} */ (root.querySelector('#apps-family'));
  if (!group) return false;
  group.hidden = false;
  if (!group.open) group.open = true; // the toggle event fills the cards
  const target = PARTS[part] && root.querySelector(`#${PARTS[part]}`);
  /** @type {HTMLElement} */ (target || group).scrollIntoView?.({ block: 'start' });
  return true;
}

/** The three states People shows; a request that fails says "unknown", never a guess. */
export async function familyStates() {
  const get = (url) => Promise.resolve().then(() => api.get(url)).catch(() => null);
  const [ff, fc, fs] = await Promise.all([get('/api/family-filter'), get('/api/docker/catalog/office-suite/family'), get('/api/family-signin')]);
  const filtered = ff ? Object.values(ff.people || {}).filter((p) => (p?.devices || []).length).length : 0;
  return {
    filter: !ff ? 'unknown' : ff.has_password && ff.user ? (filtered ? 'on' : 'ready') : 'off',
    filtered,
    calendar: !fc ? 'unknown' : !fc.installed ? 'off' : fc.running ? 'on' : 'stopped',
    signin: !fs ? 'unknown' : !fs.enabled ? 'off' : fs.running ? 'on' : 'starting',
  };
}

export function stateText(part, st) {
  const v = st[part];
  if (v === 'unknown') return t('pf.unknown', "Couldn't read its state");
  if (part === 'filter') {
    if (v === 'on') return t('pf.filter_on', '{n, plural, one {# person filtered} other {# people filtered}}', { n: st.filtered });
    return v === 'ready' ? t('pf.filter_ready', 'Connected; nobody filtered yet') : t('pf.not_set_up', 'Not set up');
  }
  if (part === 'calendar') return v === 'on' ? t('pf.on', 'On') : v === 'stopped' ? t('pf.stopped', 'The office suite is stopped') : t('pf.not_set_up', 'Not set up');
  return v === 'on' ? t('pf.on', 'On') : v === 'starting' ? t('pf.starting', 'Starting') : t('pf.not_set_up', 'Not set up');
}

export function familyLinksHtml(st) {
  const row = (part, name) =>
    `<li class="pf-row"><span class="pf-text"><strong>${escapeHtml(name)}</strong><span class="invite-meta">${escapeHtml(stateText(part, st))}</span></span><button type="button" class="btn-pill-toggle is-small" data-open-family="${part}">${escapeHtml(t('pf.open', 'Open in Apps'))}</button></li>`;
  return `<ul class="pf-rows">${row('filter', t('ff.title', "Filter the kids' devices"))}${row('calendar', t('fc.title', 'Family calendar and contacts'))}${row('signin', t('fs.title', "One sign-in for the family's apps"))}</ul>`;
}

/** People's link rows: their state, and a button that opens the card in Apps. */
export async function renderFamilyLinks(mount) {
  if (!mount) return null;
  const st = await familyStates();
  mount.innerHTML = familyLinksHtml(st);
  mount.onclick = (e) => {
    const b = /** @type {HTMLElement | null} */ (/** @type {HTMLElement} */ (e.target).closest('[data-open-family]'));
    if (b) /** @type {any} */ (window).openContainersManager?.({ view: 'family', part: b.dataset.openFamily });
  };
  return st;
}
