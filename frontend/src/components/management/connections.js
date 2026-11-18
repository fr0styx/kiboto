/**
 * Connections (SET-23, Settings decision 8): the Redfish switch for server-monitoring tools. It was
 * off by default and could be turned on through the API only (B5).
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { showToast } from '../../toast.js';

export async function renderRedfishCard(mount = document.getElementById('conn-redfish-card')) {
  if (!mount) return;
  let on;
  try {
    on = Boolean((await api.get('/api/system/redfish'))?.enabled);
  } catch {
    mount.textContent = t('conn.redfish_unknown', "Couldn't read whether Redfish is on.");
    return;
  }
  const title = Object.assign(document.createElement('div'), { className: 'kb-title' });
  title.textContent = t('conn.redfish_title', 'Redfish for monitoring tools');
  const desc = Object.assign(document.createElement('p'), { className: 'kb-sub' });
  desc.textContent = t(
    'conn.redfish_desc',
    'Lets server-monitoring tools read temperatures, fans and drives over Redfish. They sign in with a Kiboto account or an API token. Leave it off unless you use such a tool.'
  );
  const label = Object.assign(document.createElement('label'), { className: 'conn-switch' });
  const input = Object.assign(document.createElement('input'), {
    type: 'checkbox',
    checked: on,
    id: 'conn-redfish-on',
  });
  const word = document.createElement('span');
  word.textContent = t('conn.redfish_on', 'Answer Redfish requests');
  label.append(input, word);
  input.addEventListener('change', async () => {
    input.disabled = true;
    try {
      const res = await api.put('/api/system/redfish', { enabled: input.checked });
      input.checked = Boolean(res?.enabled);
      showToast(
        input.checked ? t('conn.redfish_saved_on', 'Redfish is on.') : t('conn.redfish_saved_off', 'Redfish is off.'),
        'success'
      );
    } catch (e) {
      input.checked = !input.checked;
      showToast(t('conn.redfish_fail', "Redfish wasn't changed: {error}", { error: e?.message || '' }), 'error');
    } finally {
      input.disabled = false;
    }
  });
  mount.replaceChildren(title, desc, label);
}
