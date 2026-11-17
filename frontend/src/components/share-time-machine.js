// "Backups from a Mac" on Shared folders (Shares R3): the folders Macs back up to, each with its size
// limit, a way to change or stop it, and the steps on the Mac. Where the host runs the shares
// (Unraid, TrueNAS) the host makes these folders; the section then says so and keeps the steps.
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { showToast, showPromptToast } from '../toast.js';

/** The section's markup. */
export function timeMachineHtml(data, host = '') {
  const folders = Array.isArray(data?.folders) ? data.folders : [];
  const steps = `<ol class="tm-steps">
      <li>${escapeHtml(t('tm.step1', 'On the Mac, open System Settings → General → Time Machine.'))}</li>
      <li>${escapeHtml(t('tm.step2', 'Choose "Add Backup Disk" and pick the folder from this NAS.'))}</li>
      <li>${escapeHtml(t('tm.step3', 'Sign in with your Kiboto name and password when the Mac asks.'))}</li>
    </ol>`;
  let body;
  if (host) {
    body = `<p class="kb-muted">${escapeHtml(t('tm.host', '{host} makes the folders Macs back up to. Then:', { host }))}</p>`;
  } else if (!folders.length) {
    body = `<p class="kb-muted">${escapeHtml(t('tm.none', 'No folder takes Mac backups yet.'))}</p>
      <button type="button" class="btn-pill-toggle is-primary" data-tm-make>${escapeHtml(t('tm.make', 'Make a folder for Mac backups'))}</button>`;
  } else {
    body = `<ul class="tm-list">${folders
      .map((f) => `<li><strong>${escapeHtml(f.name)}</strong> <span class="kb-muted">${escapeHtml(f.size_gb ? t('tm.limit', 'up to {gb} GB', { gb: f.size_gb }) : t('tm.no_limit', 'no size limit'))}</span>
        <button type="button" class="btn-pill-toggle is-small" data-tm-size="${escapeHtml(f.name)}">${escapeHtml(t('tm.change', 'Change the size'))}</button>
        <button type="button" class="btn-pill-toggle is-small" data-tm-stop="${escapeHtml(f.name)}">${escapeHtml(t('tm.stop', 'Stop Mac backups'))}</button></li>`)
      .join('')}</ul>`;
  }
  return `<h3 class="tm-h">${escapeHtml(t('tm.title', 'Backups from a Mac'))}</h3>${body}${steps}`;
}

async function save(name, sizeGb, redraw) {
  try {
    await api.put(`/api/storage/shares/${encodeURIComponent(name)}/time-machine`, { size_gb: sizeGb });
    showToast(sizeGb ? t('tm.saved', 'Macs can now back up to {name}, up to {gb} GB.', { name, gb: sizeGb }) : t('tm.stopped', 'Macs no longer back up to {name}. The backups already there stay.', { name }), 'success');
  } catch (err) {
    showToast(/** @type {Error} */ (err).message, 'error');
  }
  await redraw();
}

/**
 * Draws the section at the end of Shared folders.
 * @param {HTMLElement | null} container the shares page
 * @param {string} host the host's name where it runs the shares, else ''
 * @param {() => void} makeFolder opens the dialog for a new folder
 */
export async function renderTimeMachine(container, host = '', makeFolder = () => {}) {
  if (!container) return;
  let box = /** @type {HTMLElement | null} */ (container.querySelector('#tm-section'));
  if (!box) {
    box = document.createElement('section');
    box.id = 'tm-section';
    box.className = 'tm-section';
    container.appendChild(box);
  }
  let data = { managed: false, folders: [] };
  if (!host) {
    try {
      data = await api.get('/api/storage/time-machine');
    } catch {
      box.remove(); // not someone who manages shares
      return;
    }
  }
  const section = box;
  section.innerHTML = timeMachineHtml(data, host);
  const redraw = () => renderTimeMachine(container, host, makeFolder);
  section.querySelector('[data-tm-make]')?.addEventListener('click', () => {
    makeFolder();
    const tm = /** @type {HTMLInputElement | null} */ (document.getElementById('create-share-timemachine'));
    if (tm) tm.checked = true;
  });
  section.querySelectorAll('[data-tm-size]').forEach((b) => b.addEventListener('click', () => {
    const name = /** @type {HTMLElement} */ (b).dataset.tmSize || '';
    showPromptToast(t('tm.size_title', 'Size limit for {name}', { name }), t('tm.size_ask', 'How many GB may the Mac backups take?'), '', (value) => {
      const gb = parseInt(String(value || ''), 10);
      if (gb > 0) save(name, gb, redraw);
    });
  }));
  section.querySelectorAll('[data-tm-stop]').forEach((b) => b.addEventListener('click', () => save(/** @type {HTMLElement} */ (b).dataset.tmStop || '', 0, redraw)));
}
