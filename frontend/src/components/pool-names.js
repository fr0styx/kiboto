// Names the server gives on its own (the generic Linux layer's main pool, the default share's
// description) are shown in the reader's language; names people chose stay as written.
import { t } from '../i18n.js';

/** @param {string | undefined | null} name */
export function poolName(name) {
  if (name === 'Primary Storage Pool') return t('storage.main_pool_name', 'Main storage pool');
  return name || '';
}

/** @param {string | undefined | null} comment */
export function shareComment(comment) {
  if (comment === 'Kiboto Primary Storage Pool') return t('storage.main_pool_share', 'The main storage pool');
  return comment || '';
}

/** "Read only" or "Read and write" for an SFTP user or the WebDAV server. */
export function accessWords(readOnly) {
  return readOnly ? t('sftp.read_only', 'Read only') : t('sftp.read_write', 'Read and write');
}
