/**
 * Drive replacement guide (audit A11, owner decision 16 Nov 2026): what to do, step by step, when a
 * drive should be replaced or a new one goes into an empty bay. A guide only: Kiboto changes nothing
 * on the pools; the system that owns them (Unraid, TrueNAS, or Linux tools) does the rebuild.
 * Loaded on demand from the bay picture.
 */
import { t } from '../i18n.js';
import { escapeHtml } from '../utils.js';

const OWNERS = { unraid: 'Unraid', truenas: 'TrueNAS' };

/** The steps, as plain sentences, for kind "replace" (a drive in a bay) or "add" (an empty bay). */
export function guideSteps(kind, platform, drive = {}, place = '') {
  const p = OWNERS[platform] ? platform : 'other';
  const serial = drive.serial ? String(drive.serial).slice(-4) : '';
  const steps = [t('dg.backup', 'Before you start: check that your important files have a copy (Backup, "Are your files safe?").')];
  if (kind === 'replace') {
    steps.push(serial
      ? t('dg.which_serial', 'The drive: {model} in {place}, serial ending {serial}. "Find this drive" lights its bay.', { model: drive.model || drive.dev || '', place, serial })
      : t('dg.which', 'The drive: {model} in {place}. "Find this drive" lights its bay.', { model: drive.model || drive.dev || '', place }));
    steps.push(t('dg.buy', 'Get a new drive at least as large ({size}). A NAS drive (CMR, not SMR) of the same kind is the safe choice.', { size: drive.size_formatted || drive.size || '?' }));
    if (p === 'unraid') {
      steps.push(t('dg.unraid_size', "Unraid: a data drive's replacement can't be larger than the parity drive; a new parity drive must be at least as large as the largest data drive."));
      steps.push(t('dg.unraid_stop', 'In Unraid, open Main and stop the array.'));
      steps.push(t('dg.swap', 'Shut the server down, swap the drive in {place}, and start the server again.', { place }));
      steps.push(t('dg.unraid_assign', 'In Unraid Main, choose the new drive for the slot the old one had, then start the array. Unraid rebuilds it from parity; your files stay readable meanwhile. Keep the server on until the rebuild has finished.'));
    } else if (p === 'truenas') {
      steps.push(t('dg.truenas_offline', 'In TrueNAS, open Storage, then your pool, Manage Devices, the drive, and choose Offline.'));
      steps.push(t('dg.swap', 'Shut the server down, swap the drive in {place}, and start the server again.', { place }));
      steps.push(t('dg.truenas_replace', 'In TrueNAS, choose Replace on the missing drive and pick the new one. TrueNAS resilvers the pool; keep the server on until it has finished.'));
    } else {
      steps.push(t('dg.other_kind', 'How the pool rebuilds depends on how it was made (btrfs, mdadm or ZFS); Storage, Advanced shows its type. Kiboto does not rebuild pools by itself yet.'));
      steps.push(t('dg.swap', 'Shut the server down, swap the drive in {place}, and start the server again.', { place }));
      steps.push(t('dg.other_rebuild', "Rebuild with the pool's own tool (btrfs replace, mdadm --add, or zpool replace). Don't erase the old drive until the new one holds the data."));
    }
    steps.push(t('dg.after', 'Afterwards the new drive appears here. If its bay looks wrong, set it in "Which drive is in which bay".'));
  } else {
    steps.push(t('dg.add_put', 'Shut the server down, put the new drive in {place}, and start the server again.', { place }));
    if (p === 'unraid') steps.push(t('dg.unraid_add', 'In Unraid Main, stop the array, choose the new drive for an empty data slot, and start the array. Unraid clears it first; it can be no larger than the parity drive.'));
    else if (p === 'truenas') steps.push(t('dg.truenas_add', 'In TrueNAS, open Storage and add the drive to a pool (Add VDEV) or make a new pool with it.'));
    else steps.push(t('dg.other_add', 'In Kiboto, Storage, Advanced: create a pool with the new drive, or add it to a pool with that pool\'s own tool.'));
    steps.push(t('dg.after', 'Afterwards the new drive appears here. If its bay looks wrong, set it in "Which drive is in which bay".'));
  }
  return steps;
}

/** The dialog: title, who does the work, numbered steps, Close. Returns the dialog element. */
export function openDriveGuide({ kind = 'replace', platform = '', drive = {}, place = '' } = {}) {
  document.getElementById('drive-guide-dialog')?.remove();
  const dlg = document.createElement('dialog');
  dlg.id = 'drive-guide-dialog';
  dlg.className = 'drive-guide';
  dlg.setAttribute('aria-labelledby', 'drive-guide-title');
  const title = kind === 'replace' ? t('dg.title_replace', 'Replace this drive') : t('dg.title_add', 'Add a drive here');
  const owner = OWNERS[platform] || '';
  const who = owner
    ? t('dg.who', '{owner} does the work; these are the steps. Kiboto changes nothing on your pools.', { owner })
    : t('dg.who_other', 'These are the steps. Kiboto changes nothing on your pools.');
  dlg.innerHTML = `
    <h2 id="drive-guide-title" class="drive-guide-title">${escapeHtml(title)}</h2>
    <p class="drive-guide-who">${escapeHtml(who)}</p>
    <ol class="drive-guide-steps">${guideSteps(kind, platform, drive, place).map((s) => `<li>${escapeHtml(s)}</li>`).join('')}</ol>
    <div class="drive-guide-actions"><button type="button" class="btn-pill-toggle is-primary" data-dg-close>${escapeHtml(t('dg.close', 'Close'))}</button></div>`;
  document.body.append(dlg);
  const close = () => { if (typeof dlg.close === 'function' && dlg.open) dlg.close(); dlg.remove(); };
  dlg.querySelector('[data-dg-close]')?.addEventListener('click', close);
  dlg.addEventListener('cancel', (e) => { e.preventDefault(); close(); });
  if (typeof dlg.showModal === 'function') dlg.showModal();
  else dlg.setAttribute('open', '');
  /** @type {HTMLElement | null} */ (dlg.querySelector('[data-dg-close]'))?.focus();
  return dlg;
}
