/**
 * Replace a drive (Storage, a ZFS or btrfs pool that keeps a second copy, where Kiboto manages
 * the pools): choose the drive to replace and an empty one; the pool's own tool rebuilds onto it
 * while the pool stays in use. Loaded on demand from the pool's button.
 */
import { api } from '../api.js';
import { formatFixed, formatNumber } from '../format.js';
import { html } from '../html.js';
import { t } from '../i18n.js';
import { editionLine } from '../edition-line.js';

const POLL_MS = 5000;

/** Why a pool cannot rebuild, in words. */
export function whyNot(why) {
  if (why === 'no_copy')
    return t(
      'dr.why_no_copy',
      'This pool keeps no second copy of its files, so it cannot rebuild onto a new drive. Its files come back from a backup.'
    );
  if (why === 'one_drive')
    return t('dr.why_one_drive', 'This pool is on one drive. Its files come back from a backup onto a new pool.');
  return t('dr.why_other', "Kiboto cannot read this pool's drives right now.");
}

/** The line about a rebuild that runs now, or "" when none does. */
export function progressText(progress) {
  if (!progress || !progress.running) return '';
  return typeof progress.percent === 'number'
    ? t('dr.running', 'Rebuilding: {percent}% done. The pool stays in use; keep the server on.', {
        percent: Math.floor(progress.percent),
      })
    : t('dr.running_unknown', 'Rebuilding. The pool stays in use; keep the server on.');
}

function size(bytes) {
  const gb = (Number(bytes) || 0) / 1e9;
  return gb >= 1000 ? `${formatFixed(gb / 1000, 1)} TB` : `${formatNumber(Math.round(gb))} GB`;
}

/** The dialog's body for a plan from GET /api/storage/pools/{id}/replace. */
export function bodyHtml(plan) {
  const running = progressText(plan.progress);
  if (running) return html`<p class="dr-progress" id="dr-progress" aria-live="polite">${running}</p>`;
  if (!plan.can) return html`<p class="dr-why">${whyNot(plan.why)}</p>`;
  const members = plan.members || [];
  const broken = members.find((m) => m.state !== 'ONLINE');
  const oldRows = members.map(
    (m, i) =>
      html`<label class="dr-choice"
        ><input type="radio" name="dr-old" value="${m.id}" ${(broken ? m === broken : i === 0) ? 'checked' : ''} />
        <span translate="no">${m.label}</span> <span class="dr-state" translate="no">${m.state}</span></label
      >`
  );
  const newRows = (plan.drives || []).map(
    (d, i) =>
      html`<label class="dr-choice"
        ><input type="radio" name="dr-new" value="${d.path}" ${i === 0 ? 'checked' : ''} />
        <span translate="no">${[d.model, d.serial].filter(Boolean).join(' ') || d.dev}</span> ${size(d.size_bytes)}</label
      >`
  );
  return html`<p class="dr-intro">
      ${t(
        'dr.intro',
        "The pool rebuilds onto the new drive while it stays in use. Keep the server on until it has finished; don't take out the old drive before."
      )}
    </p>
    <fieldset class="dr-set">
      <legend>${t('dr.old', 'Drive to replace')}</legend>
      ${oldRows}
    </fieldset>
    <fieldset class="dr-set">
      <legend>${t('dr.new', 'New drive (empty, at least as large)')}</legend>
      ${
        newRows.length
          ? newRows
          : html`<p class="dr-none">
            ${t('dr.none', 'No empty drive large enough is connected. Put the new drive in, then open this again.')}
          </p>`
      }
    </fieldset>`;
}

/** Opens the dialog for a pool; `done` runs after a rebuild was started. Returns the dialog. */
export async function openDriveReplace(poolId, poolName = '', done = () => {}) {
  document.getElementById('drive-replace-dialog')?.remove();
  const dlg = document.createElement('dialog');
  dlg.id = 'drive-replace-dialog';
  dlg.className = 'drive-guide';
  dlg.setAttribute('aria-labelledby', 'dr-title');
  const url = `/api/storage/pools/${encodeURIComponent(poolId)}/replace`;
  let timer = null;
  const close = () => {
    if (timer) clearTimeout(timer);
    if (typeof dlg.close === 'function' && dlg.open) dlg.close();
    dlg.remove();
  };
  const draw = (plan, error = '') => {
    const canStart = plan && plan.can && !progressText(plan.progress) && (plan.drives || []).length > 0;
    dlg.innerHTML = html`<h2 id="dr-title" class="drive-guide-title">
        ${t('dr.title', 'Replace a drive of {pool}', { pool: poolName || poolId })}
      </h2>
      ${plan && editionLine(plan.edition) ? html`<p class="dr-edition">${editionLine(plan.edition)}</p>` : ''}
      ${plan ? bodyHtml(plan) : ''}
      <p class="fw-error" id="dr-error" role="alert" ${error ? '' : 'hidden'}>${error}</p>
      <div class="drive-guide-actions">
        ${
          canStart
            ? html`<button type="button" class="btn-pill-toggle is-danger" id="dr-start">${t('dr.start', 'Replace')}</button>`
            : ''
        }
        <button type="button" class="btn-pill-toggle is-primary" data-dr-close>${t('dg.close', 'Close')}</button>
      </div>`;
    dlg.querySelector('[data-dr-close]')?.addEventListener('click', close);
    dlg.querySelector('#dr-start')?.addEventListener('click', start);
    if (plan && progressText(plan.progress)) timer = setTimeout(refresh, POLL_MS);
  };
  const refresh = async () => {
    timer = null;
    if (!dlg.isConnected) return;
    try {
      draw(await api.get(url));
    } catch (e) {
      draw(null, e instanceof Error ? e.message : String(e));
    }
  };
  async function start() {
    const old = /** @type {HTMLInputElement | null} */ (dlg.querySelector('input[name="dr-old"]:checked'))?.value;
    const fresh = /** @type {HTMLInputElement | null} */ (dlg.querySelector('input[name="dr-new"]:checked'))?.value;
    if (!old || !fresh) return;
    const button = /** @type {HTMLButtonElement | null} */ (dlg.querySelector('#dr-start'));
    if (button) button.disabled = true;
    try {
      await api.post(url, { old, new: fresh });
      done();
      await refresh();
    } catch (e) {
      if (/** @type {any} */ (e)?.error === 'cancelled') {
        if (button) button.disabled = false;
        return;
      }
      const box = /** @type {HTMLElement | null} */ (dlg.querySelector('#dr-error'));
      if (box) {
        box.textContent = e instanceof Error ? e.message : String(e);
        box.hidden = false;
      }
      if (button) button.disabled = false;
    }
  }
  dlg.addEventListener('cancel', (e) => {
    e.preventDefault();
    close();
  });
  document.body.append(dlg);
  draw(null);
  if (typeof dlg.showModal === 'function') dlg.showModal();
  else dlg.setAttribute('open', '');
  await refresh();
  return dlg;
}
