/**
 * A USB disk was plugged in (FEAT-07): back the NAS up to it when backups go there, and import
 * its photos and videos when it holds a camera folder. One prompt per disk and plug-in.
 */
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { showToast, showConfirmToast } from '../toast.js';

let _shownTs = null;

/** The prompts that fit a disk, in order: backup first, then the photo import. */
export function offersFor(disk) {
  if (!disk || !disk.path) return [];
  const out = [];
  if ((disk.backups || []).length) out.push('backup');
  if (disk.media) out.push('import');
  if (disk.setup) out.push('setup'); // Backup 5: an empty disk, used for backups in one step
  return out;
}

/** Backup 5: "Use this disk for backups?" opens "Protect this NAS" with the disk already chosen. */
function askSetup(disk, next) {
  const name = disk.name || disk.path;
  showConfirmToast(
    t('usb.setup_title', 'Use this disk for backups?'),
    t('usb.setup_msg', '{name} has no backups yet. Keep a copy of this NAS on it, brought up to date every night?', {
      name,
    }),
    async () => {
      const m = await import('./protect-nas.js');
      await m.openProtectGuide(`usb|${disk.path}`);
      next();
    },
    async () => {
      await api.post('/api/usb/dismiss').catch(() => {});
      next();
    },
    { isMedia: true, okText: t('usb.setup_ok', 'Set it up'), cancelText: t('media.btn_dismiss', 'Dismiss') }
  );
}

function ask(disk, kind, rest) {
  if (kind === 'setup') {
    askSetup(disk, () => rest.length && ask(disk, rest[0], rest.slice(1)));
    return;
  }
  const name = escapeHtml(disk.name || disk.path);
  const backups = (disk.backups || []).map((b) => escapeHtml(b.name || b.id)).join(', ');
  const title =
    kind === 'backup'
      ? t('usb.backup_title', 'Back up the NAS to this disk?')
      : t('usb.import_title', 'Import photos from this disk?');
  const msg =
    kind === 'backup'
      ? t('usb.backup_msg', '{name} holds these backups: {list}. Bring them up to date now?', { name, list: backups })
      : disk.import_dest
        ? t(
            'usb.import_msg_to',
            '{name} has a camera folder. Copy its photos and videos into dated folders in {dest}, each file checked after copying?',
            { name, dest: escapeHtml(disk.import_dest) }
          )
        : t(
            'usb.import_msg',
            '{name} has a camera folder. Copy its photos and videos into dated folders, each file checked after copying?',
            { name }
          );
  const next = () => {
    if (rest.length) ask(disk, rest[0], rest.slice(1));
  };
  showConfirmToast(
    title,
    msg,
    async () => {
      try {
        if (kind === 'backup') {
          await api.post('/api/usb/backup', { path: disk.path });
          showToast(t('usb.backup_started', 'Backing up to {name}; it shows in Jobs.', { name: disk.name }), 'info');
        } else {
          await api.post('/api/usb/import', { path: disk.path });
          showToast(t('usb.import_started', 'Importing from {name}…', { name: disk.name }), 'info');
        }
      } catch (err) {
        showToast(err.message || String(err), 'error');
      }
      next();
    },
    async () => {
      if (!rest.length) await api.post('/api/usb/dismiss').catch(() => {});
      next();
    },
    {
      isMedia: true,
      okText: kind === 'backup' ? t('usb.backup_now', 'Back up now') : t('usb.import_now', 'Import photos'),
      cancelText: t('media.btn_dismiss', 'Dismiss'),
    }
  );
}

/** Called with copy_state.pending_usb on every stats update. */
export function handlePendingUsb(disk) {
  if (!disk || !disk.ts || disk.ts === _shownTs) return;
  const offers = offersFor(disk);
  if (!offers.length) return;
  _shownTs = disk.ts;
  ask(disk, offers[0], offers.slice(1));
}

export function resetUsbOffer() {
  _shownTs = null;
}
