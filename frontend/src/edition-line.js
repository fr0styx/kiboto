/**
 * The line a card shows when the feature table (docs/feature-matrix.json, read by the server from
 * backend/edition_features.json) says this edition does a thing differently: still being checked,
 * done by the NAS system, not offered, or not there yet. '' when it simply works here.
 */
import { t } from './i18n.js';

export function editionLine(state) {
  switch (state) {
    case 'check':
      return t('edl.check', 'Built for this edition, and still being checked.');
    case 'host':
      return t('edl.host', 'Your NAS system does this here.');
    case 'no':
      return t('edl.no', 'Not offered on this edition.');
    case 'soon':
      return t('edl.soon', 'Not on this edition yet.');
    default:
      return '';
  }
}
