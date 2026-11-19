// Apps -> Docker cleanup: "Space each app uses" (re-audit R4). Docker's own numbers come at once;
// an app's folders on the NAS are measured when asked, and never on a sleeping drive.
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { formatBytes } from '../../format.js';

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

/** What a row says after the app's name: its data, then the program, then what was left out. */
export function appSpaceLine(app) {
  const parts = [
    t('dk.space_data', '{size} of data', { size: formatBytes(app.data_bytes || 0) }),
    t('dk.space_program', 'program {size}', { size: formatBytes(app.program_bytes || 0) }),
  ];
  const states = (app.folders || []).map((f) => f.state);
  if (states.includes('not_measured')) parts.push(t('dk.space_not_measured', 'its folders are not measured yet'));
  if (states.includes('asleep')) parts.push(t('dk.space_asleep', 'a folder is on a sleeping drive and was left alone'));
  if (states.includes('partial')) parts.push(t('dk.space_partial', 'a folder took too long and is counted in part'));
  if (app.shared_folders) parts.push(t('dk.space_shared', 'shared folders are not counted'));
  return parts.join(' · ');
}

export function appSpaceNodes(result) {
  const apps = (result && result.apps) || [];
  if (!apps.length) return [el('p', 'kb-muted', t('dk.space_none', 'No apps are installed.'))];
  const list = el('ul', 'dpm-space-list');
  for (const app of apps) {
    const item = el('li', 'dpm-space-row');
    const name = el('strong', '', app.name);
    name.setAttribute('translate', 'no');
    item.append(name, el('span', 'kb-muted', appSpaceLine(app)));
    list.append(item);
  }
  return [list];
}

/** Fills the box with Docker's numbers, and offers to measure the folders. */
export async function loadAppSpace(box = document.getElementById('dpm-app-space'), folders = false) {
  if (!box) return null;
  const body = box.querySelector('.dpm-space-body') || box.appendChild(el('div', 'dpm-space-body'));
  body.textContent = folders
    ? t('dk.space_measuring', 'Measuring the folders… this can take up to 20 seconds.')
    : t('common.loading', 'Loading…');
  try {
    const result = await api.get(`/api/docker/apps/space${folders ? '?folders=true' : ''}`);
    body.replaceChildren(...appSpaceNodes(result));
    if (!result.folders_measured && result.apps.length) {
      const more = el('button', 'btn-pill-toggle is-small', t('dk.space_measure', 'Measure the folders too'));
      more.type = 'button';
      more.addEventListener('click', () => loadAppSpace(box, true));
      body.append(more);
    }
    return result;
  } catch (e) {
    body.textContent = t('dk.space_failed', "The apps' space couldn't be read: {error}", { error: e?.message || '' });
    return null;
  }
}
