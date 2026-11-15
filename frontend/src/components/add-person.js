// Add a person in three short steps (SET-19 stage 4c, Users report section 5): who they are, what
// they can use, how they get in (an account made now, or an invite link). One flow for every role;
// "Add another like Mia" starts over with the same role, folders and limits.
import { api, apiFetch } from '../api.js';
import { escapeHtml, trapFocus, copyText } from '../utils.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { shareChoicesHtml, grantShares } from './share-access.js';

export const MAIN_ROLES = () => [
  ['superadmin', t('ap.role_admin', 'Administrator'), t('ap.role_admin_d', 'Everything: people, settings, and every private folder')],
  ['share_user', t('ap.role_member', 'Family member'), t('ap.role_member_d', 'Their own folder and the shared folders you choose')],
  ['kid', t('ap.role_kid', 'Kid'), t('ap.role_kid_d', 'Their own folder, the folders you choose, and limits')],
  ['guest', t('ap.role_guest', 'Guest'), t('ap.role_guest_d', 'Can look at the shared folders you choose')],
];
export const MORE_ROLES = () => [
  ['app_operator', t('ap.role_apps', 'App manager'), t('ap.role_apps_d', 'Installs and runs apps, and can give an app most data folders')],
  ['storage_admin', t('ap.role_storage', 'Storage admin'), t('ap.role_storage_d', 'Drives, pools and shares, and can open every private folder')],
  ['backup_operator', t('ap.role_backup', 'Backup manager'), t('ap.role_backup_d', "Backups and cloud copies; can bring back anyone's files and save the recovery kit")],
  ['auditor', t('ap.role_viewer', 'Viewer'), t('ap.role_viewer_d', "Can look, can't change")],
];
const INVITABLE = ['share_user', 'kid', 'guest', 'backup_operator', 'app_operator', 'auditor'];
export const canInvite = (role) => INVITABLE.includes(role);
export const canLimit = (role) => !['superadmin', 'storage_admin'].includes(role);

/** A sign-in name from a name: lower case, no accents or spaces, at most 32 characters. */
export function suggestUsername(name) {
  const plain = String(name || '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9_.-]/g, '')
    .replace(/^[^a-z_]+/, '')
    .slice(0, 32);
  return plain.length >= 2 ? plain : '';
}

/** A fresh flow, or one like the last person (role, folders, limits kept, name cleared). */
export function newState(like = null) {
  return {
    step: 1,
    name: '',
    role: like?.role || 'share_user',
    shares: { ...(like?.shares || {}) },
    hours: like?.hours || null,
    quotaGb: like?.quotaGb || 0,
    how: like?.how || 'create',
    username: '',
    password: '',
    mustChange: true,
    days: 7,
    done: null,
  };
}

const h = (key, en, params) => escapeHtml(t(key, en, params));

function rolesHtml(list, chosen) {
  return list
    .map(([id, name, line]) => `<label class="ap-role"><input type="radio" name="ap-role" value="${id}"${id === chosen ? ' checked' : ''}><span class="ap-role-name">${escapeHtml(name)}</span><span class="ap-role-line">${escapeHtml(line)}</span></label>`)
    .join('');
}

/** The dialog's inside for the current step. */
export function stepHtml(st, shares) {
  const head = `<h2 class="account-h" id="ap-title">${h('ap.title', 'Add a person')}</h2>`;
  if (st.done) {
    const body = st.done.link
      ? `<p class="ap-line">${h('ap.link_ready', 'Send this link to {name}. It works once, for {days} days.', { name: st.done.name, days: st.days })}</p>
         <code class="ap-link">${escapeHtml(st.done.link)}</code>
         <div class="ap-actions"><button type="button" class="btn-pill-toggle" data-ap-copy="link">${h('ap.copy_link', 'Copy link')}</button><button type="button" class="btn-pill-toggle" data-ap-copy="message">${h('ap.copy_message', 'Copy message')}</button></div>`
      : `<p class="ap-line">${h('ap.added', '{name} was added.', { name: st.done.name })}</p>`;
    return `${head}${body}<div class="ap-actions"><button type="button" class="btn-pill-toggle" data-ap-again>${h('ap.again', 'Add another like {name}', { name: st.done.name })}</button><button type="button" class="btn-pill-toggle is-primary" data-ap-close>${h('ap.close', 'Done')}</button></div>`;
  }
  const names = [t('ap.step1', 'Who'), t('ap.step2', 'What they can use'), t('ap.step3', 'How they get in')];
  const progress = `<p class="ap-step">${h('ap.step_of', 'Step {n} of 3: {what}', { n: st.step, what: names[st.step - 1] })}</p>`;
  let body;
  if (st.step === 1) {
    const more = MORE_ROLES().some(([id]) => id === st.role);
    body = `<label class="ap-field">${h('ap.name', 'Name')}<input type="text" class="tz-text-input" data-ap-name maxlength="80" value="${escapeHtml(st.name)}" autocomplete="off"></label>
      <fieldset class="ap-roles"><legend>${h('ap.role', 'Role')}</legend>${rolesHtml(MAIN_ROLES(), st.role)}
        <details class="ap-more"${more ? ' open' : ''}><summary>${h('ap.more_roles', 'More roles')}</summary>${rolesHtml(MORE_ROLES(), st.role)}</details>
      </fieldset>`;
  } else if (st.step === 2) {
    body = `${shares.length ? `<fieldset class="ap-shares"><legend>${h('ap.folders', 'Shared folders')}</legend>${shareChoicesHtml(shares)}</fieldset>` : ''}
      <div data-ap-hours-wrap${canLimit(st.role) ? '' : ' hidden'}><p class="ap-sub">${h('ap.hours', 'Sign-in hours')}</p><div data-ap-hours></div></div>
      <details class="ap-more"><summary>${h('ap.more', 'More')}</summary><label class="ap-field">${h('pp.quota', 'Storage limit (GB, empty = no limit)')}<input type="number" min="0" class="tz-text-input" data-ap-quota value="${st.quotaGb || ''}"></label></details>`;
  } else {
    const invite = canInvite(st.role);
    body = `<fieldset class="ap-how"><legend>${h('ap.how', 'How they get in')}</legend>
        <label class="ap-role"><input type="radio" name="ap-how" value="create"${st.how === 'create' || !invite ? ' checked' : ''}><span class="ap-role-name">${h('ap.create', 'Create the account now')}</span><span class="ap-role-line">${h('ap.create_d', 'You choose a sign-in name and a first password.')}</span></label>
        <label class="ap-role"><input type="radio" name="ap-how" value="invite"${st.how === 'invite' && invite ? ' checked' : ''}${invite ? '' : ' disabled'}><span class="ap-role-name">${h('ap.invite', 'Send an invite link')}</span><span class="ap-role-line">${invite ? h('ap.invite_d', 'They choose their own sign-in name and password.') : h('ap.invite_no', 'Not for this role: create the account now.')}</span></label>
      </fieldset>
      <div data-ap-create${st.how === 'invite' && invite ? ' hidden' : ''}>
        <label class="ap-field">${h('ap.username', 'Sign-in name')}<input type="text" class="tz-text-input" data-ap-username maxlength="32" value="${escapeHtml(st.username || suggestUsername(st.name))}" autocomplete="off"></label>
        <label class="ap-field">${h('ap.password', 'First password (8 characters or more)')}<input type="password" class="tz-text-input" data-ap-password minlength="8" autocomplete="new-password"></label>
        <label class="udg-check"><input type="checkbox" data-ap-must${st.mustChange ? ' checked' : ''}> <span>${h('users.f_must_change', 'They choose their own password when they first sign in')}</span></label>
      </div>
      <div data-ap-invite${st.how === 'invite' && invite ? '' : ' hidden'}>
        <label class="ap-field">${h('ap.days', 'The link works for (days)')}<input type="number" min="1" max="90" class="tz-text-input" data-ap-days value="${st.days}"></label>
      </div>`;
  }
  const back = st.step > 1 ? `<button type="button" class="btn-pill-toggle" data-ap-back>${h('ap.back', 'Back')}</button>` : `<button type="button" class="btn-pill-toggle" data-ap-close>${h('ap.cancel', 'Cancel')}</button>`;
  const next = st.step < 3 ? h('ap.next', 'Next') : st.how === 'invite' && canInvite(st.role) ? h('ap.make_link', 'Create the invite link') : h('ap.add', 'Add {name}', { name: st.name });
  return `${head}${progress}<div class="ap-body">${body}</div><div class="ap-actions">${back}<button type="submit" class="btn-pill-toggle is-primary" data-ap-next>${next}</button></div>`;
}

/** The message to paste into a chat with the link. */
export function inviteMessage(name, link) {
  return t('ap.message', 'Hi {name}, here is your invite to our NAS: {link} Open it, choose a name and a password, and you are in.', { name, link });
}

/** Reads the current step's fields into the state; returns a problem to show, or ''. */
export function readStep(form, st, hoursMod) {
  const q = (sel) => /** @type {HTMLInputElement | null} */ (form.querySelector(sel));
  if (st.step === 1) {
    st.name = (q('[data-ap-name]')?.value || '').trim();
    st.role = /** @type {HTMLInputElement | null} */ (form.querySelector('input[name="ap-role"]:checked'))?.value || st.role;
    if (!st.name) return t('ap.need_name', 'Write their name first.');
  } else if (st.step === 2) {
    st.shares = {};
    form.querySelectorAll('select[data-add-user-share]').forEach((el) => {
      const sel = /** @type {HTMLSelectElement} */ (el);
      if (sel.value && sel.value !== 'none') st.shares[sel.dataset.addUserShare || ''] = sel.value;
    });
    const box = form.querySelector('[data-ap-hours]');
    st.hours = canLimit(st.role) && hoursMod && box ? hoursMod.readHours(box) : null;
    if (st.hours && !Object.keys(st.hours).length) st.hours = null;
    st.quotaGb = parseInt(q('[data-ap-quota]')?.value || '0', 10) || 0;
  } else {
    st.how = /** @type {HTMLInputElement | null} */ (form.querySelector('input[name="ap-how"]:checked'))?.value || 'create';
    st.username = (q('[data-ap-username]')?.value || '').trim().toLowerCase();
    st.password = q('[data-ap-password]')?.value || '';
    st.mustChange = Boolean(q('[data-ap-must]')?.checked);
    st.days = parseInt(q('[data-ap-days]')?.value || '7', 10) || 7;
    if (st.how === 'create' && (!st.username || st.password.length < 8)) return t('ap.need_login', 'Choose a sign-in name and a password of 8 characters or more.');
  }
  return '';
}

/** Makes the account or the invite. Returns {name, link?}. */
export async function finish(st) {
  if (st.how === 'invite' && canInvite(st.role)) {
    const r = await api.post('/api/invites', { role_id: st.role, note: st.name, days: st.days, quota_gb: st.quotaGb, max_uses: 1, shares: st.shares, signin_hours: st.hours });
    return { name: st.name, link: `${window.location.origin}${window.location.pathname}${String(r.link || '').replace(/^\//, '')}` };
  }
  const res = await apiFetch('/api/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ username: st.username, display_name: st.name, password: st.password, role_id: st.role, storage_quota_bytes: st.quotaGb > 0 ? st.quotaGb * 1024 ** 3 : 0, must_change_password: st.mustChange }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  await grantShares(st.username, st.shares);
  if (st.hours && body.user?.id) {
    await apiFetch(`/api/users/${body.user.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ signin_hours: st.hours }) });
  }
  return { name: st.name };
}

/**
 * Opens the flow; onDone() runs after each person is added (the list reloads itself too).
 * @param {{ onDone?: () => void }} [opts]
 */
export async function openAddPerson({ onDone } = {}, doc = document) {
  const shares = (await Promise.resolve().then(() => api.get('/api/storage/share-access')).catch(() => null))?.shares || []; // only for who manages folders
  const hoursMod = await import('./signin-hours.js');
  const back = /** @type {HTMLElement | null} */ (doc.activeElement);
  const wrap = Object.assign(doc.createElement('div'), { className: 'ap-backdrop' });
  wrap.innerHTML = '<form class="ap-dialog" role="dialog" aria-modal="true" aria-labelledby="ap-title" novalidate></form>';
  doc.body.append(wrap);
  const form = /** @type {HTMLFormElement} */ (wrap.firstElementChild);
  let st = newState();
  let release = () => {};
  const close = () => {
    release();
    wrap.remove();
    back?.focus?.();
  };
  const draw = () => {
    form.innerHTML = stepHtml(st, shares);
    if (st.step === 2 && !st.done) {
      Object.entries(st.shares).forEach(([name, lvl]) => {
        const sel = /** @type {HTMLSelectElement | null} */ (form.querySelector(`select[data-add-user-share="${CSS.escape(name)}"]`));
        if (sel) sel.value = lvl;
      });
      hoursMod.installSigninHours(form.querySelector('[data-ap-hours]'), st.hours ? { signin_hours: st.hours } : null, { canBeLimited: canLimit(st.role) });
    }
    form.querySelectorAll('input[name="ap-how"]').forEach((r) =>
      r.addEventListener('change', () => {
        const invite = /** @type {HTMLInputElement} */ (r).value === 'invite';
        /** @type {HTMLElement} */ (form.querySelector('[data-ap-create]')).hidden = invite;
        /** @type {HTMLElement} */ (form.querySelector('[data-ap-invite]')).hidden = !invite;
      }),
    );
    release();
    release = trapFocus(form, close);
    /** @type {HTMLElement | null} */ (form.querySelector('input:not([type="radio"]):not([hidden]), [data-ap-close], [data-ap-next]'))?.focus();
  };
  form.addEventListener('click', async (e) => {
    const el = /** @type {HTMLElement} */ (e.target).closest('button');
    if (!el) return;
    if (el.hasAttribute('data-ap-close')) close();
    else if (el.hasAttribute('data-ap-back')) {
      st.step -= 1;
      draw();
    } else if (el.hasAttribute('data-ap-again')) {
      st = newState(st);
      draw();
    } else if (el.dataset.apCopy) {
      const text = el.dataset.apCopy === 'link' ? st.done.link : inviteMessage(st.done.name, st.done.link);
      copyText(text).then(() => showToast(t('ap.copied', 'Copied.'), 'info'));
    }
  });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const problem = readStep(form, st, hoursMod);
    if (problem) {
      showToast(problem, 'error');
      return;
    }
    if (st.step < 3) {
      st.step += 1;
      draw();
      return;
    }
    try {
      st.done = await finish(st);
      onDone?.();
      draw();
    } catch (err) {
      showToast(/** @type {Error} */ (err).message, 'error');
    }
  });
  draw();
  return wrap;
}
