/**
 * Security: "Checks that use the internet" (owner, 19 Nov 2026). Each asks a service outside the
 * home, so each is off until an administrator turns it on, and each line says what is sent.
 */
import { api } from '../../api.js';
import { showToast } from '../../toast.js';
import { t } from '../../i18n.js';

/** What each check is called and what it sends; a check this page doesn't know is not shown. */
export const WORDS = {
  weakness_feed: () => [
    t('sec.oc_weak', 'Warn about apps with a weakness that is being attacked'),
    t(
      'sec.oc_weak_desc',
      "Once a day Kiboto downloads the public list of weaknesses that attackers are using (from CISA, a US government agency) and compares it here with your apps. Nothing about your NAS is sent; the site sees your home's internet address."
    ),
  ],
  internet_speed: () => [
    t('sec.oc_inet', 'Test the internet line'),
    t(
      'sec.oc_inet_desc',
      "Adds a button on the Network page. When you press it, the NAS fetches and sends test data to Cloudflare's speed test, which sees your home's internet address and nothing else. Nothing runs by itself."
    ),
  ],
  leaked_passwords: () => [
    t('sec.oc_leaked', 'Refuse passwords found in known data leaks'),
    t(
      'sec.oc_leaked_desc',
      'When someone sets a password, Kiboto asks Have I Been Pwned whether it has leaked. Only the first 5 of the 40 characters of a fingerprint of the password are sent, never the password.'
    ),
  ],
};

export function outsideChecksNodes(checks) {
  const nodes = [];
  for (const c of checks || []) {
    if (!WORDS[c.name]) continue;
    const [title, desc] = WORDS[c.name]();
    const box = Object.assign(document.createElement('input'), { type: 'checkbox', checked: !!c.enabled });
    box.dataset.outsideCheck = c.name;
    const strong = Object.assign(document.createElement('strong'), { textContent: title });
    const note = Object.assign(document.createElement('span'), { className: 'immich-note', textContent: desc });
    const label = document.createElement('label');
    label.className = 'sec-oc-row';
    const words = document.createElement('span');
    words.className = 'sec-oc-words';
    words.append(strong, note);
    label.append(box, words);
    nodes.push(label);
  }
  return nodes;
}

export async function renderOutsideChecks() {
  const anchor = document.getElementById('sec-mfa-policy') || document.getElementById('sec-advisor-card');
  if (!anchor) return false;
  let box = document.getElementById('sec-outside-checks');
  if (!box) {
    box = document.createElement('div');
    box.id = 'sec-outside-checks';
    box.className = 'sec-advisor-card';
    anchor.after(box);
  }
  let view;
  try {
    view = await api.get('/api/security/outside-checks');
  } catch {
    box.hidden = true; // not an administrator, or an older server
    return false;
  }
  box.hidden = false;
  const title = Object.assign(document.createElement('h4'), {
    textContent: t('sec.oc_title', 'Checks that use the internet'),
  });
  const intro = Object.assign(document.createElement('p'), {
    className: 'immich-note',
    textContent: t(
      'sec.oc_intro',
      'Each of these asks a service outside your home, so each is off until you turn it on. Every line says what is sent.'
    ),
  });
  const rows = document.createElement('div');
  rows.className = 'sec-col-xs';
  rows.append(...outsideChecksNodes(view.checks));
  box.replaceChildren(title, intro, rows);
  if (!box.dataset.bound) {
    box.dataset.bound = '1';
    box.addEventListener('change', async (e) => {
      const input = /** @type {HTMLInputElement} */ (e.target);
      const name = input.dataset?.outsideCheck;
      if (!name) return;
      try {
        await api.put('/api/security/outside-checks', { name, enabled: input.checked });
        showToast(
          input.checked ? t('sec.oc_on', 'Turned on.') : t('sec.oc_off', 'Turned off. Nothing more is asked.'),
          'success'
        );
      } catch (err) {
        input.checked = !input.checked;
        showToast(t('sec.oc_failed', "Couldn't change it: {error}", { error: err?.message || '' }), 'error');
      }
    });
  }
  return true;
}
