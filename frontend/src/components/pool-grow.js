/**
 * Add a drive (Storage, a ZFS or btrfs pool, where Kiboto manages the pools): choose how the pool
 * grows and the empty drive(s); the pool's own tool adds them and copies onto them while the pool
 * stays in use. Loaded on demand from the pool's button.
 */
import { api } from '../api.js';
import { formatFixed, formatNumber } from '../format.js';
import { html } from '../html.js';
import { t } from '../i18n.js';

const POLL_MS = 5000;

/** Why a pool cannot take a drive now, in words. */
export function whyNot(why) {
  if (why === 'not_healthy')
    return t('pg.why_not_healthy', 'A drive of this pool is missing or failing. Replace it first, then add drives.');
  if (why === 'cannot_grow') return t('pg.why_cannot', 'This kind of pool cannot take another drive.');
  return t('pg.why_other', "Kiboto cannot read this pool's drives right now.");
}

/** The line about copying that runs now, or "" when none does. */
export function progressText(progress) {
  if (!progress || !progress.running) return '';
  return typeof progress.percent === 'number'
    ? t('pg.running', 'Copying onto the new drive: {percent}% done. The pool stays in use; keep the server on.', {
        percent: Math.floor(progress.percent),
      })
    : t('pg.running_unknown', 'Copying onto the new drive. The pool stays in use; keep the server on.');
}

/** A drive's lasting name as a person reads it: /dev/disk/by-id/ata-WDC_WD80EFZZ_7SGX1234-part1 ->
 *  WDC WD80EFZZ 7SGX1234. A group (raidz1-0) or a plain path stays as it is. */
export function driveName(label) {
  const s = String(label || '');
  if (!s.startsWith('/dev/disk/by-id/')) return s;
  return s
    .slice('/dev/disk/by-id/'.length)
    .replace(/-part\d+$/, '')
    .replace(/^(ata|nvme|scsi|usb|wwn|virtio)-/, '')
    .replace(/-\d+:\d+$/, '')
    .replace(/_/g, ' ');
}

/** What one way of growing does, in a sentence. */
export function wayText(way) {
  const drive = driveName(way.label);
  if (way.way === 'mirror')
    return t('pg.way_mirror', 'Make a mirror of {drive}: every file is kept twice. It gives no more space.', { drive });
  if (way.way === 'add_mirror')
    return t('pg.way_add_mirror', 'Add a mirror of two drives: more space, and every file is still kept twice.');
  if (way.way === 'widen')
    return t('pg.way_widen', 'Widen {drive} by one drive: more space, the same protection. This cannot be undone.', {
      drive,
    });
  return ['single', ''].includes(way.profile || '')
    ? t('pg.way_add_single', 'Add one drive: more space. Each file is still kept once.')
    : t('pg.way_add_spread', 'Add one drive: more space. The files are spread over it in the background.');
}

function size(bytes) {
  const gb = (Number(bytes) || 0) / 1e9;
  return gb >= 1000 ? `${formatFixed(gb / 1000, 1)} TB` : `${formatNumber(Math.round(gb))} GB`;
}

/** The dialog's body for a plan from GET /api/storage/pools/{id}/grow. */
export function bodyHtml(plan) {
  const running = progressText(plan.progress);
  if (running) return html`<p class="dr-progress" id="pg-progress" aria-live="polite">${running}</p>`;
  const ways = plan.ways || [];
  if (!ways.length) return html`<p class="dr-why">${whyNot(plan.why)}</p>`;
  const wayRows = ways.map(
    (w, i) =>
      html`<label class="pg-choice"
        ><input type="radio" name="pg-way" value="${String(i)}" ${i === 0 ? 'checked' : ''} />
        <span>${wayText(w)}</span></label
      >`
  );
  const driveRows = (plan.drives || []).map(
    (d) =>
      html`<label class="pg-choice"
        ><input type="checkbox" name="pg-drive" value="${d.path}" data-size="${String(d.size_bytes || 0)}" />
        <span translate="no">${[d.model, d.serial].filter(Boolean).join(' ') || d.dev}</span> ${size(d.size_bytes)}</label
      >`
  );
  return html`<p class="dr-intro">
      ${t(
        'pg.intro',
        'The drives must be empty. The pool stays in use while it copies onto them; keep the server on until it has finished.'
      )}
    </p>
    <fieldset class="dr-set">
      <legend>${t('pg.how', 'How the pool grows')}</legend>
      ${wayRows}
    </fieldset>
    <fieldset class="dr-set">
      <legend id="pg-drives-legend">${t('pg.drives', 'Empty drives')}</legend>
      ${
        driveRows.length
          ? driveRows
          : html`<p class="dr-none">${t('pg.none', 'No empty drive is connected. Put the new drive in, then open this again.')}</p>`
      }
    </fieldset>`;
}

/** Which way is chosen, the drives ticked, and whether that is enough to start. */
export function choice(dlg, plan) {
  const i = Number(/** @type {HTMLInputElement | null} */ (dlg.querySelector('input[name="pg-way"]:checked'))?.value);
  const way = (plan?.ways || [])[Number.isInteger(i) ? i : -1];
  const drives = [...dlg.querySelectorAll('input[name="pg-drive"]:checked')].map(
    (el) => /** @type {HTMLInputElement} */ (el).value
  );
  return { way, drives, ready: Boolean(way) && drives.length === way.count };
}

/** Drives too small for the chosen way are greyed out; the legend says how many to choose. */
export function follow(dlg, plan) {
  const { way } = choice(dlg, plan);
  for (const el of dlg.querySelectorAll('input[name="pg-drive"]')) {
    const box = /** @type {HTMLInputElement} */ (el);
    box.disabled = Boolean(way) && Number(box.dataset.size) < (way?.min || 0);
    if (box.disabled) box.checked = false;
  }
  const legend = dlg.querySelector('#pg-drives-legend');
  if (legend && way)
    legend.textContent =
      way.count === 2
        ? t('pg.choose_two', 'Empty drives: choose two of the same size')
        : t('pg.choose_one', 'Empty drives: choose one, at least as large as the pool’s drives');
  const start = /** @type {HTMLButtonElement | null} */ (dlg.querySelector('#pg-start'));
  if (start) start.disabled = !choice(dlg, plan).ready; // after too-small drives were unticked
}

/** Opens the dialog for a pool; `done` runs after drives were added. Returns the dialog. */
export async function openPoolGrow(poolId, poolName = '', done = () => {}) {
  document.getElementById('pool-grow-dialog')?.remove();
  const dlg = document.createElement('dialog');
  dlg.id = 'pool-grow-dialog';
  dlg.className = 'drive-guide';
  dlg.setAttribute('aria-labelledby', 'pg-title');
  const url = `/api/storage/pools/${encodeURIComponent(poolId)}/grow`;
  let timer = null;
  let plan = null;
  const close = () => {
    if (timer) clearTimeout(timer);
    if (typeof dlg.close === 'function' && dlg.open) dlg.close();
    dlg.remove();
  };
  const draw = (next, error = '') => {
    plan = next;
    const canStart = plan && (plan.ways || []).length && !progressText(plan.progress) && (plan.drives || []).length;
    dlg.innerHTML = html`<h2 id="pg-title" class="drive-guide-title">
        ${t('pg.title', 'Add a drive to {pool}', { pool: poolName || poolId })}
      </h2>
      ${plan ? bodyHtml(plan) : ''}
      <p class="fw-error" id="pg-error" role="alert" ${error ? '' : 'hidden'}>${error}</p>
      <div class="drive-guide-actions">
        ${canStart ? html`<button type="button" class="btn-pill-toggle is-danger" id="pg-start" disabled>${t('pg.start', 'Add')}</button>` : ''}
        <button type="button" class="btn-pill-toggle is-primary" data-pg-close>${t('dg.close', 'Close')}</button>
      </div>`;
    dlg.querySelector('[data-pg-close]')?.addEventListener('click', close);
    dlg.querySelector('#pg-start')?.addEventListener('click', start);
    dlg
      .querySelectorAll('input[name="pg-way"], input[name="pg-drive"]')
      .forEach((el) => el.addEventListener('change', () => follow(dlg, plan)));
    if (plan) follow(dlg, plan);
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
    const { way, drives, ready } = choice(dlg, plan);
    if (!ready || !way) return;
    const button = /** @type {HTMLButtonElement | null} */ (dlg.querySelector('#pg-start'));
    if (button) button.disabled = true;
    try {
      await api.post(url, { way: way.way, to: way.to || '', drives });
      done();
      await refresh();
    } catch (e) {
      if (/** @type {any} */ (e)?.error === 'cancelled') {
        if (button) button.disabled = false;
        return;
      }
      const box = /** @type {HTMLElement | null} */ (dlg.querySelector('#pg-error'));
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
