// A person's page (SET-19 stage 4b, Users report section 5): opened from their row in People. It
// replaces the "Edit person" dialog and the row's icons: who they are, what they can use, their
// limits, how they sign in, their data, and turning off or removing them, in one place.
import { api, apiFetch } from '../api.js';
import { escapeHtml, copyText } from '../utils.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { roleChange, showRole } from './role-change.js';
import { formatDateTime } from '../format.js';

const GB = 1024 ** 3;
const UNLIMITABLE = ['superadmin', 'storage_admin']; // roles that manage people get no hours

/** Whether this person can have sign-in hours and a family filter. */
export function canBeLimited(user) {
  return !UNLIMITABLE.includes(user.role_id);
}

/** The page's sections; the parts other modules fill have their own mounts. */
export function personPageHtml(user, { me, roleName }) {
  const isSelf = Boolean(me && me.id === user.id);
  const active = user.status === 'active';
  const nextStatus = active ? 'disabled' : 'active'; // the status Turn off / Turn on sets
  const name = user.display_name || user.username;
  const quota = user.storage_quota_bytes > 0 ? Math.round(user.storage_quota_bytes / GB) : '';
  const h = (key, en, params) => escapeHtml(t(key, en, params));
  return `<div class="pp-head">
      <button type="button" class="btn-pill-toggle is-small" data-pp-back>${h('pp.back', 'All people')}</button>
      <h3 class="account-h" id="pp-title" tabindex="-1">${escapeHtml(name)}</h3>
      <p class="pp-sub">${h('pp.signs_in_as', 'Signs in as {name}', { name: user.username })} · ${escapeHtml(roleName)}</p>
    </div>
    <form class="pp-section" data-pp-form aria-labelledby="pp-who">
      <h4 class="pp-h" id="pp-who">${h('pp.who', 'Who they are')}</h4>
      <label class="pp-field">${h('pp.name', 'Name')}<input type="text" class="tz-text-input" data-pp-name maxlength="80" value="${escapeHtml(user.display_name || '')}"></label>
      <label class="pp-field">${h('pp.email', 'Email')}<input type="email" class="tz-text-input" data-pp-email value="${escapeHtml(user.email || '')}"></label>
      <label class="pp-field">${h('pp.role', 'Role')}<select class="tz-select-input" data-pp-role${isSelf ? ' disabled' : ''}></select></label>
      <h4 class="pp-h">${h('pp.access', 'What they can use')}</h4>
      <label class="pp-field">${h('pp.quota', 'Storage limit (GB, empty = no limit)')}<input type="number" min="0" class="tz-text-input" data-pp-quota value="${quota}"></label>
      <div data-pp-hours-wrap${canBeLimited(user) ? '' : ' hidden'}>
        <h4 class="pp-h">${h('pp.limits', 'Limits')}</h4>
        <div data-pp-hours></div>
      </div>
      <button type="submit" class="btn-pill-toggle is-primary">${h('users.save_changes', 'Save changes')}</button>
    </form>
    <section class="pp-section" aria-labelledby="pp-signin">
      <h4 class="pp-h" id="pp-signin">${h('pp.signin', 'How they sign in')}</h4>
      <p class="pp-line">${user.mfa_enabled ? h('pp.two_step_on', 'Two-step sign-in is on.') : h('pp.two_step_off', 'Two-step sign-in is off.')}</p>
      <div class="pp-actions"><button type="button" class="btn-pill-toggle" data-pp-reset>${h('pp.reset_pw', 'Set a new password')}</button></div>
      <h5 class="pp-h5">${h('pp.devices', 'Where they are signed in')}</h5>
      <ul class="pp-devices" data-pp-devices><li class="pp-line">${h('users.sessions_loading', 'Loading sign-ins…')}</li></ul>
      <div data-pp-signin-anchor></div>
    </section>
    <section class="pp-section" data-pp-away hidden aria-labelledby="pp-away-h">
      <h4 class="pp-h" id="pp-away-h">${h('pp.away', 'Apps away from home')}</h4>
      <p class="pp-line">${h('pp.away_desc', 'A link that signs them in to the family sign-in for apps once, to add a passkey there.')}</p>
      <div class="pp-actions"><button type="button" class="btn-pill-toggle" data-pp-link>${h('pp.copy_link', 'Copy a sign-in link')}</button></div>
    </section>
    <section class="pp-section" aria-labelledby="pp-data-h">
      <h4 class="pp-h" id="pp-data-h">${h('pp.data', 'Their data')}</h4>
      <div data-pp-data-anchor></div>
    </section>
    ${
      isSelf
        ? ''
        : `<section class="pp-section" aria-labelledby="pp-end-h">
      <h4 class="pp-h" id="pp-end-h">${h('pp.end', 'Turn off or remove')}</h4>
      <div class="pp-actions">
        <button type="button" class="btn-pill-toggle" data-pp-status="${nextStatus}">${active ? h('users.turn_off', 'Turn off this account') : h('users.turn_on', 'Turn on this account')}</button>
        <button type="button" class="btn-pill-toggle is-danger" data-pp-remove>${h('pp.remove', 'Remove {name}…', { name })}</button>
      </div>
    </section>`
    }`;
}

/** The devices list, read from the server (never the session secrets). */
export function devicesHtml(sessions) {
  if (!sessions.length) return `<li class="pp-line">${escapeHtml(t('pp.no_devices', 'Not signed in anywhere.'))}</li>`;
  return sessions
    .map((s) => {
      const when = s.last_active_at ? formatDateTime(s.last_active_at * 1000) : '';
      return `<li class="pp-device"><span>${escapeHtml(s.user_agent || t('pp.unknown_device', 'Unknown browser'))}</span><span class="pp-line">${escapeHtml([s.ip_address, when].filter(Boolean).join(' · '))}</span></li>`;
    })
    .join('');
}

/** What Save sends: only what the form says, the role only when changed (SET-10). */
export function saveBody(form, user, hours) {
  const val = (sel) => /** @type {HTMLInputElement} */ (form.querySelector(sel)).value;
  const gb = parseInt(val('[data-pp-quota]') || '0', 10);
  return {
    display_name: val('[data-pp-name]').trim(),
    email: val('[data-pp-email]').trim(),
    ...roleChange(val('[data-pp-role]'), user.role_id),
    storage_quota_bytes: gb > 0 ? gb * GB : 0,
    ...(hours ? { signin_hours: hours } : {}),
  };
}

let _back = null;

/** Back to the list. */
export function closePersonPage(doc = document) {
  const page = doc.getElementById('person-page');
  const list = doc.getElementById('users-pane-list');
  if (page) page.hidden = true;
  if (list) list.hidden = false;
  _back?.focus?.();
  _back = null;
}

async function fillDevices(page, user) {
  const box = page.querySelector('[data-pp-devices]');
  try {
    const r = await api.get(`/api/users/${encodeURIComponent(user.id)}/sessions`);
    box.innerHTML = devicesHtml(r?.sessions || []);
  } catch {
    box.innerHTML = `<li class="pp-line">${escapeHtml(t('pp.devices_failed', "Couldn't read where they are signed in."))}</li>`;
  }
}

async function offerAppLink(page, user) {
  try {
    const st = await api.get('/api/family-signin');
    if (!st?.enabled || user.status !== 'active') return;
  } catch {
    return; // no right to it, or not set up: no link
  }
  const away = /** @type {HTMLElement} */ (page.querySelector('[data-pp-away]'));
  away.hidden = false;
  /** @type {HTMLElement} */ (away.querySelector('[data-pp-link]')).onclick = async () => {
    try {
      const r = await api.post(`/api/family-signin/users/${encodeURIComponent(user.id)}/link`, {});
      await copyText(r.url);
      showToast(t('pp.link_copied', 'Sign-in link copied. It works once, for 24 hours.'), 'success');
    } catch (err) {
      showToast(/** @type {Error} */ (err).message, 'error');
    }
  };
}

/**
 * Opens the person's page in place of the list.
 * deps: { me, roleName(id), roleOptionsHtml, reload(), resetPassword(id, name), setStatus(id, status), remove(id, name) }
 */
export async function openPersonPage(user, deps, doc = document) {
  const list = doc.getElementById('users-pane-list');
  if (!list || !user) return null;
  let page = doc.getElementById('person-page');
  if (!page) {
    page = Object.assign(doc.createElement('section'), { id: 'person-page', className: 'person-page' });
    page.setAttribute('aria-labelledby', 'pp-title');
    list.insertAdjacentElement('afterend', page);
  }
  _back = /** @type {HTMLElement | null} */ (doc.activeElement);
  page.innerHTML = personPageHtml(user, { me: deps.me, roleName: deps.roleName(user.role_id) });
  const select = /** @type {HTMLSelectElement} */ (page.querySelector('[data-pp-role]'));
  select.innerHTML = deps.roleOptionsHtml || '';
  showRole(select, user.role_id, deps.roleName(user.role_id));
  list.hidden = true;
  page.hidden = false;
  /** @type {HTMLElement} */ (page.querySelector('#pp-title')).focus();

  /** @type {HTMLElement} */ (page.querySelector('[data-pp-back]')).onclick = () => closePersonPage(doc);
  /** @type {HTMLElement} */ (page.querySelector('[data-pp-reset]')).onclick = () =>
    deps.resetPassword(user.id, user.username);
  const status = /** @type {HTMLElement | null} */ (page.querySelector('[data-pp-status]'));
  if (status)
    status.onclick = async () => {
      await deps.setStatus(user.id, status.dataset.ppStatus);
      closePersonPage(doc);
    };
  const remove = /** @type {HTMLElement | null} */ (page.querySelector('[data-pp-remove]'));
  if (remove) remove.onclick = () => deps.remove(user.id, user.username);

  const hoursBox = page.querySelector('[data-pp-hours]');
  const hours = canBeLimited(user) ? await import('./signin-hours.js') : null;
  const hoursChanged = hours ? hours.installSigninHours(hoursBox, user, { canBeLimited: true }) : () => false;
  const form = /** @type {HTMLFormElement} */ (page.querySelector('[data-pp-form]'));
  form.onsubmit = async (e) => {
    e.preventDefault();
    const body = saveBody(form, user, hours && hoursChanged() ? hours.readHours(hoursBox) : null);
    try {
      const res = await apiFetch(`/api/users/${user.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
      showToast(t('toast.user_updated_successfully', 'User updated successfully.'), 'success');
      deps.reload();
    } catch (err) {
      showToast(t('toast.error', 'Error: {detail}', { detail: /** @type {Error} */ (err).message }), 'error');
    }
  };

  // the parts other modules already make: passkeys, a lost phone, their data
  const signin = page.querySelector('[data-pp-signin-anchor]');
  const data = page.querySelector('[data-pp-data-anchor]');
  import('./passkeys-card.js').then((m) => m.installPasskeyResetFor(signin, user)).catch(() => {});
  import('./management/lost-device.js').then((m) => m.installLostDeviceFor(signin, user, deps.me)).catch(() => {});
  import('./management/user-data.js').then((m) => m.installUserDataFor(data, user)).catch(() => {});
  fillDevices(page, user);
  offerAppLink(page, user);
  return page;
}
