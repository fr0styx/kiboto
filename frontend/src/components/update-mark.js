/**
 * The daily update check, seen from Settings (Settings decision 5): a mark on General when a newer
 * Kiboto is ready, and the "Check for updates every day" switch on its Software update card.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';

export async function refreshUpdateMark(root = document) {
  let st;
  try {
    st = await api.get('/api/system/update-watch');
  } catch {
    return null; // someone who may not see it, or no answer: no mark
  }
  const mark = /** @type {HTMLElement | null} */ (root.getElementById('mgmt-sidebar-update-badge'));
  if (mark) {
    mark.hidden = !st.available;
    mark.title = st.available
      ? t('updates.mark_title', 'Version {version} is ready', { version: st.latest || '' })
      : '';
  }
  const box = /** @type {HTMLInputElement | null} */ (root.getElementById('update-daily-toggle'));
  if (box) {
    box.checked = Boolean(st.daily);
    if (!box.dataset.wired) {
      box.dataset.wired = '1';
      box.addEventListener('change', async () => {
        try {
          await api.put('/api/system/update-watch', { daily: box.checked });
        } catch (e) {
          box.checked = !box.checked;
          showToast(t('updates.daily_failed', "That wasn't changed: {error}", { error: e?.message || '' }), 'error');
        }
      });
    }
  }
  return st;
}
