/**
 * What restoring an app backup says (SET-14). It said "successfully restored (0 paths
 * restored)" every time: the count was read from a field the server does not send, and the
 * server said the app was recreated when nothing had started.
 */
import { t } from '../../i18n.js';

/** [text, kind] for the result of POST /api/backup/apps/{id}/restore. */
export function restoredSaid(result, app) {
  const r = result || {};
  const count = Array.isArray(r.restored_mounts) ? r.restored_mounts.length : 0;
  const values = { app, count, path: r.compose_path || '' };
  switch (r.outcome) {
    case 'running_again':
      return [
        t(
          'apprest.running',
          '"{app}" was restored ({count, plural, one {# folder} other {# folders}}) and runs again.',
          values
        ),
        'success',
      ];
    case 'stopped_kept':
      return [
        t(
          'apprest.stopped',
          '"{app}" was restored ({count, plural, one {# folder} other {# folders}}). It was stopped before and stays stopped.',
          values
        ),
        'success',
      ];
    case 'brought_back':
      return [
        t(
          'apprest.brought_back',
          '"{app}" was restored ({count, plural, one {# folder} other {# folders}}) and started again from its saved Compose file.',
          values
        ),
        'success',
      ];
    case 'needs_review':
      return [
        t(
          'apprest.needs_review',
          'The folders of "{app}" were restored ({count}). Its saved Compose file asks for host-level access, so Kiboto did not start it by itself; the file is kept at {path}.',
          values
        ),
        'warn',
      ];
    case 'bring_back_failed':
      return [
        t(
          'apprest.bring_back_failed',
          'The folders of "{app}" were restored ({count}), but the app did not start again and nothing was left half-done. Its Compose file is kept at {path}.',
          values
        ),
        'warn',
      ];
    case 'start_failed':
      return [
        t(
          'apprest.start_failed',
          '"{app}" was restored ({count, plural, one {# folder} other {# folders}}), but it did not start again. Start it from Apps.',
          values
        ),
        'warn',
      ];
    default:
      return [
        values.path
          ? t(
              'apprest.files_only',
              'The folders of "{app}" were restored ({count}), but the app itself is not installed any more. Install it again from the catalog; its Compose file is kept at {path}.',
              values
            )
          : t(
              'apprest.files_only_short',
              'The folders of "{app}" were restored ({count}), but the app itself is not installed any more. Install it again from the catalog.',
              values
            ),
        'warn',
      ];
  }
}
