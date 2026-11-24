/**
 * General -> Front panel (SET-30, Hardware decision 2 a): the front light and the front screen,
 * each with one On/Off row, on machines that have them. Everything else stays on Hardware, an
 * Advanced page, linked from here.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { state } from '../state.js';
import { ROUTES } from '../router.js';

/** Which of the two the machine has, from the live stats' hardware facts. */
export function frontPanelParts(stats = state.latestStats) {
  const hw = (stats && stats.hardware) || {};
  return { light: Boolean(hw.has_mcu || hw.is_zettlabs), screen: Boolean(hw.has_lcd) };
}

function row(id, label, on, onChange) {
  const wrap = document.createElement('label');
  wrap.className = 'front-panel-row';
  wrap.htmlFor = id;
  const text = document.createElement('span');
  text.textContent = label;
  const box = Object.assign(document.createElement('input'), { type: 'checkbox', id, checked: on });
  box.addEventListener('change', async () => {
    box.disabled = true;
    try {
      await onChange(box.checked);
    } catch (e) {
      box.checked = !box.checked;
      showToast(t('front.failed', "That wasn't changed: {error}", { error: e?.message || '' }), 'error');
    } finally {
      box.disabled = false;
    }
  });
  wrap.append(text, box);
  return wrap;
}

/** The front light's On/Off row (POST /api/led {power}). */
export async function lightRow(id) {
  let on = true;
  try {
    on = ((await api.get('/api/led')) || {}).power !== 'off';
  } catch {
    /* not readable: shown as on, as the light usually is */
  }
  return row(id, t('front.light', 'Front light'), on, (v) => api.post('/api/led', { power: v ? 'on' : 'off' }));
}

/** The front screen's On/Off row (POST /api/screen {power}). */
export async function screenRow(id) {
  let on = true;
  try {
    on = ((await api.get('/api/screen')) || {}).power !== false;
  } catch {
    /* as above */
  }
  return row(id, t('front.screen', 'Front screen'), on, (v) => api.post('/api/screen', { power: v }));
}

/** On/Off first in the Hardware page's Lights and Front screen sections (Hardware 2), once each. */
export async function renderHardwarePower(doc = document, stats = state.latestStats) {
  const parts = frontPanelParts(stats);
  const light = doc.getElementById('hw-light-power');
  const screen = doc.getElementById('hw-screen-power');
  if (light && parts.light && !light.firstChild) light.append(await lightRow('hw-light-on'));
  if (screen && parts.screen && !screen.firstChild) screen.append(await screenRow('hw-screen-on'));
}

export async function renderFrontPanel(
  mount = document.getElementById('general-front-panel'),
  stats = state.latestStats
) {
  if (!mount) return false;
  const parts = frontPanelParts(stats);
  if (!parts.light && !parts.screen) {
    mount.hidden = true;
    return false;
  }
  const title = Object.assign(document.createElement('div'), { className: 'kb-title' });
  title.textContent = t('front.title', 'Front panel');
  /** @type {HTMLElement[]} */
  const kids = [title];
  if (parts.light) kids.push(await lightRow('front-light-on'));
  if (parts.screen) kids.push(await screenRow('front-screen-on'));
  const more = Object.assign(document.createElement('button'), {
    type: 'button',
    className: 'btn-pill-toggle front-panel-more',
  });
  more.textContent = t('front.more', 'Colours, brightness and night times');
  more.addEventListener('click', () => ROUTES.hardware?.());
  kids.push(more);
  mount.replaceChildren(...kids);
  mount.hidden = false;
  return true;
}
