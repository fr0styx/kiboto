/**
 * "Add your own app" (Apps decision 3, designed with the Compose apply of decision 4b): a name and a
 * Compose file, checked by the server (what would be created, any access to the host), confirmed,
 * then created through the same safe apply as the stack editor, which removes what it started if
 * a part does not come up. Replaces the old Sources and Sideload, which nobody could reach.
 */
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';
import { applyStack } from './stack-apply.js';

export const NAME_RE = /^[a-z0-9][a-z0-9_-]{0,62}$/;

/** Why a name cannot be used, or ''. */
export function nameProblem(name) {
  if (!name) return t('own.name_needed', 'Give the app a name.');
  if (!NAME_RE.test(name)) return t('own.name_bad', 'Use small letters, digits, hyphens and underscores, starting with a letter or digit.');
  return '';
}

// examples in the fields: a name and file lines are the same in every language
const NAME_EXAMPLE = 'my-app';
const ENV_EXAMPLE = 'TZ=Europe/Berlin';
const EXAMPLE = 'services:\n  web:\n    image: nginx:1.27\n    ports:\n      - "8088:80"\n    restart: unless-stopped\n';

/**
 * Opens the dialog; `done` runs after the app was created.
 * @param {{ done?: () => unknown, wait?: (ms: number) => Promise<unknown> }} [opts]
 */
export function openAddOwnApp(opts = {}) {
  document.getElementById('own-app-dialog')?.remove();
  const dlg = document.createElement('dialog');
  dlg.id = 'own-app-dialog';
  dlg.className = 'own-app-dialog';
  dlg.setAttribute('aria-labelledby', 'own-app-title');
  dlg.innerHTML = `
    <form method="dialog" class="own-app-form" id="own-app-form">
      <h2 id="own-app-title" class="own-app-title">${escapeHtml(t('own.title', 'Add your own app'))}</h2>
      <p class="own-app-help">${escapeHtml(t('own.help', 'Paste a Docker Compose file. Kiboto shows what it will create and asks before it starts anything; if a part does not come up, everything it started is removed again.'))}</p>
      <label class="own-app-field"><span>${escapeHtml(t('own.name', 'Name'))}</span>
        <input id="own-app-name" type="text" autocomplete="off" spellcheck="false" maxlength="63" placeholder="${escapeHtml(NAME_EXAMPLE)}" required></label>
      <label class="own-app-field"><span>${escapeHtml(t('own.compose', 'Compose file'))}</span>
        <textarea id="own-app-compose" rows="12" spellcheck="false" placeholder="${escapeHtml(EXAMPLE)}" required></textarea></label>
      <details class="own-app-env"><summary>${escapeHtml(t('own.env', 'Settings file (.env, optional)'))}</summary>
        <textarea id="own-app-envtext" rows="4" spellcheck="false" placeholder="${escapeHtml(ENV_EXAMPLE)}"></textarea></details>
      <p class="own-app-msg" id="own-app-msg" role="status" aria-live="polite"></p>
      <div class="own-app-actions">
        <button type="button" class="btn-pill-toggle" id="own-app-cancel">${escapeHtml(t('common.cancel', 'Cancel'))}</button>
        <button type="submit" class="btn-pill-toggle is-primary" id="own-app-go">${escapeHtml(t('own.go', 'Check and add'))}</button>
      </div>
    </form>`;
  document.body.appendChild(dlg);
  const $ = (id) => /** @type {any} */ (dlg.querySelector(`#${id}`));
  const msg = $('own-app-msg');
  const shut = () => {
    if (typeof dlg.close === 'function' && dlg.open) dlg.close();
    dlg.remove();
  };
  $('own-app-cancel').addEventListener('click', shut);
  dlg.addEventListener('close', () => dlg.remove()); // Escape
  $('own-app-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('own-app-name').value.trim();
    const compose = $('own-app-compose').value;
    const problem = nameProblem(name) || (compose.trim() ? '' : t('own.compose_needed', 'Paste the Compose file.'));
    msg.textContent = problem;
    if (problem) return;
    $('own-app-go').disabled = true;
    const ok = await applyStack(name, compose, $('own-app-envtext').value, { msg, create: true, wait: opts.wait, done: opts.done });
    $('own-app-go').disabled = false;
    if (ok) shut();
  });
  if (typeof dlg.showModal === 'function') dlg.showModal();
  else dlg.setAttribute('open', '');
  $('own-app-name').focus();
  return dlg;
}
