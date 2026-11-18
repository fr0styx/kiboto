// Household rules on People (SET-19 stage 4d, Users decision 9): "Adults must use two-step sign-in"
// as one choice, and what kids and guests may do with Kib. The list per role stays under Security.
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { showToast, showConfirmToast } from '../toast.js';
import { aiSwitchesHtml } from './kids-rules.js';

/** Everyone but kids and guests. */
export const ADULT_ROLES = ['superadmin', 'storage_admin', 'app_operator', 'backup_operator', 'auditor', 'share_user'];

/** 'off', 'adults', or 'some' (a list made under Security that is neither). */
export function twoStepMode(required) {
  const set = new Set(required || []);
  if (!set.size) return 'off';
  const adults = ADULT_ROLES.every((r) => set.has(r)) && [...set].every((r) => ADULT_ROLES.includes(r));
  return adults ? 'adults' : 'some';
}

/** How many adults have not set two-step sign-in up yet. */
export function adultsWithout(view) {
  const missing = view?.without_two_step || {};
  return ADULT_ROLES.reduce((n, r) => n + (missing[r] || 0), 0);
}

export function householdHtml(view, access) {
  const parts = [];
  if (view) {
    const mode = twoStepMode(view.required_roles);
    const n = adultsWithout(view);
    parts.push(`<div class="hh-row"><label class="hh-label" for="hh-two-step">${escapeHtml(t('hh.two_step', 'Adults must use two-step sign-in'))}</label>
      <select id="hh-two-step" class="tz-select-input" data-hh-two-step>
        <option value="off"${mode === 'off' ? ' selected' : ''}>${escapeHtml(t('hh.off', 'Off'))}</option>
        <option value="adults"${mode === 'adults' ? ' selected' : ''}>${escapeHtml(t('hh.adults', 'On, for everyone but kids and guests'))}</option>
        ${mode === 'some' ? `<option value="some" selected>${escapeHtml(t('hh.some', 'Some roles (set under Security)'))}</option>` : ''}
      </select></div>
      ${n ? `<p class="hh-note">${escapeHtml(t('hh.without', '{n, plural, one {# adult has not set it up yet.} other {# adults have not set it up yet.}}', { n }))}</p>` : ''}
      <p class="hh-note">${escapeHtml(t('hh.smb_note', 'People with two-step sign-in use a separate password for network folders, which they choose when they turn it on.'))}</p>`);
  }
  const ai = aiSwitchesHtml(access);
  if (ai) parts.push(`<h5 class="kids-sub">${escapeHtml(t('kids.ai', 'Kib, the AI helper'))}</h5>${ai}`);
  return parts.join('');
}

async function saveTwoStep(mount, select) {
  const roles = select.value === 'adults' ? ADULT_ROLES : [];
  try {
    await api.put('/api/security/mfa-policy', { required_roles: roles });
    showToast(t('hh.saved', 'Saved.'), 'success');
  } catch (err) {
    showToast(/** @type {Error} */ (err)?.message || t('hh.failed', "That didn't save."), 'error');
  }
  await renderHousehold(mount); // shows what the server has now
}

/** Fills the mount; hidden for someone who can change neither rule. */
export async function renderHousehold(mount) {
  if (!mount) return;
  const [view, access] = await Promise.all([
    Promise.resolve()
      .then(() => api.get('/api/security/mfa-policy'))
      .catch(() => null),
    Promise.resolve()
      .then(() => api.get('/api/ai/access'))
      .catch(() => null),
  ]);
  const html = householdHtml(view, access);
  const section = /** @type {HTMLElement | null} */ (mount.closest('section'));
  if (section) section.hidden = !html;
  mount.innerHTML = html;
  const select = /** @type {HTMLSelectElement | null} */ (mount.querySelector('[data-hh-two-step]'));
  if (select) {
    select.onchange = () => {
      if (select.value === 'some') return;
      const n = adultsWithout(view);
      if (select.value !== 'adults' || !n) return saveTwoStep(mount, select);
      // until they set it up, they can sign in only to do that: say so first
      showConfirmToast(
        t('sec.mfa_policy_q_title', 'Require two-step sign-in?'),
        t(
          'hh.q',
          '{n, plural, one {# adult has not set it up. Until they do, they can sign in only to set it up.} other {# adults have not set it up. Until they do, they can sign in only to set it up.}}',
          { n }
        ),
        () => saveTwoStep(mount, select),
        () => renderHousehold(mount)
      );
    };
  }
  mount.querySelectorAll('[data-kids-ai]').forEach((sw) => {
    const box = /** @type {HTMLInputElement} */ (sw);
    box.addEventListener('change', async () => {
      box.disabled = true;
      try {
        await api.put('/api/ai/access', { [box.dataset.kidsAi || '']: { [box.dataset.role || '']: box.checked } });
      } catch {
        box.checked = !box.checked;
      }
      box.disabled = false;
    });
  });
}
