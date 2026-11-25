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

/** Says On or Off beside the switch, so the row reads as a sentence. */
function stateWord(on) {
  return on ? t('front.state_on', 'On') : t('front.state_off', 'Off');
}

function row(id, label, help, on, onChange) {
  const wrap = Object.assign(document.createElement('div'), { className: 'front-panel-row' });
  const text = Object.assign(document.createElement('div'), { className: 'front-panel-text' });
  const name = Object.assign(document.createElement('span'), { className: 'front-panel-name', id: `${id}-name` });
  name.textContent = label;
  const desc = Object.assign(document.createElement('span'), { className: 'front-panel-desc', id: `${id}-desc` });
  desc.textContent = help;
  text.append(name, desc);
  const word = Object.assign(document.createElement('span'), { className: 'front-panel-state', id: `${id}-state` });
  word.textContent = stateWord(on);
  word.setAttribute('aria-hidden', 'true'); // the switch itself says on or off
  const sw = Object.assign(document.createElement('label'), { className: 'switch' });
  const box = Object.assign(document.createElement('input'), { type: 'checkbox', id, checked: on });
  box.setAttribute('role', 'switch');
  box.setAttribute('aria-labelledby', name.id);
  box.setAttribute('aria-describedby', desc.id);
  sw.append(box, Object.assign(document.createElement('span'), { className: 'toggle-slider' }));
  const show = () => {
    word.textContent = stateWord(box.checked);
    wrap.classList.toggle('is-off', !box.checked);
  };
  box.addEventListener('change', async () => {
    box.disabled = true;
    show();
    try {
      await onChange(box.checked);
    } catch (e) {
      box.checked = !box.checked;
      show();
      showToast(t('front.failed', "That wasn't changed: {error}", { error: e?.message || '' }), 'error');
    } finally {
      box.disabled = false;
    }
  });
  wrap.classList.toggle('is-off', !on);
  wrap.append(text, word, sw);
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
  return row(
    id,
    t('front.light', 'Front light'),
    t('front.light_help', 'Turns the light bar on the front of the server on or off.'),
    on,
    (v) => api.post('/api/led', { power: v ? 'on' : 'off' })
  );
}

/** The front screen's On/Off row (POST /api/screen {power}). */
export async function screenRow(id) {
  let on = true;
  try {
    on = ((await api.get('/api/screen')) || {}).power !== false;
  } catch {
    /* as above */
  }
  return row(
    id,
    t('front.screen', 'Front screen'),
    t('front.screen_help', 'Turns the small screen on the front of the server on or off.'),
    on,
    (v) => api.post('/api/screen', { power: v })
  );
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
