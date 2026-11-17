// The File Explorer's Type column in the reader's language (five-language sweep).
import { t } from '../i18n.js';

/** @param {{name: string, is_dir?: boolean}} file */
export function fileKind(file, isRemoteDir = false, isDiskDir = false) {
  if (file.is_dir) {
    if (isRemoteDir) return t('fm.kind_cloud_drive', 'Cloud drive');
    return isDiskDir ? t('fm.kind_disk_drive', 'Drive') : t('fm.kind_folder', 'Folder');
  }
  return file.name.includes('.') ? file.name.split('.').pop().toUpperCase() : t('fm.kind_file', 'File');
}
