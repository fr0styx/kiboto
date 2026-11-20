/**
 * Coloured labels on files and folders (re-audit R11). Each person has six colours, may name
 * each one, and puts one on anything they can open; the labels are kept with the account
 * (/api/fs/labels), not in the files. All explorer windows share this list and redraw on the
 * "fm:labels" event.
 */
import { api } from '../api.js';
import { ZettEventBus } from '../event-bus.js';
import { showToast } from '../toast.js';
import { t } from '../i18n.js';

export const COLOURS = ['red', 'orange', 'yellow', 'green', 'blue', 'purple'];

let _state = null;
let _loading = null;

const norm = (p) => String(p || '').replace(/\/+$/, '') || '/';

/** The colour's own word, in the reader's language. */
export function colourWord(colour) {
  const words = {
    red: () => t('fm.label_red', 'Red'),
    orange: () => t('fm.label_orange', 'Orange'),
    yellow: () => t('fm.label_yellow', 'Yellow'),
    green: () => t('fm.label_green', 'Green'),
    blue: () => t('fm.label_blue', 'Blue'),
    purple: () => t('fm.label_purple', 'Purple'),
  };
  return words[colour] ? words[colour]() : '';
}

/** What the person called this colour, or the colour's word. */
export function labelName(colour) {
  return (_state && _state.names && _state.names[colour]) || colourWord(colour);
}

/** The colour on a path, or ''. */
export function labelOf(path) {
  return (_state && _state.items && _state.items[norm(path)]) || '';
}

/** Paths that carry a colour, by name. */
export function labelledPaths(colour) {
  const items = (_state && _state.items) || {};
  return Object.keys(items)
    .filter((p) => items[p] === colour)
    .sort((a, b) => a.localeCompare(b));
}

/** The colours in use, with how many things carry each. */
export function labelsInUse() {
  return COLOURS.map((colour) => ({ colour, count: labelledPaths(colour).length })).filter((l) => l.count);
}

function set(view) {
  _state = { names: (view && view.names) || {}, items: (view && view.items) || {} };
  ZettEventBus.emit('fm:labels', _state);
  return _state;
}

export function loadLabels(force = false) {
  if (_state && !force) return Promise.resolve(_state);
  if (!_loading) {
    _loading = api
      .get('/api/fs/labels')
      .then((view) => set(view))
      .catch(() => set(_state))
      .finally(() => {
        _loading = null;
      });
  }
  return _loading;
}

/** Files were renamed or moved: the server carried their labels along, so read the list again.
 *  Only for someone who has labels; nobody else pays a request for it. */
export function labelsMayHaveMoved() {
  if (!_state || !Object.keys(_state.items).length) return Promise.resolve(_state);
  return loadLabels(true);
}
ZettEventBus.on('fm:refresh', labelsMayHaveMoved);

/** A folder was listed: when the server dropped labels of things that are gone from it (deleted
 *  over the network, outside these pages), the list is read again. */
export function labelsAfterListing(listing) {
  return listing && listing.labels_gone ? loadLabels(true) : Promise.resolve(_state);
}

/** Puts a colour on a path; no colour takes the label off. */
export async function setLabel(path, colour) {
  try {
    set(await api.put('/api/fs/labels', { path: norm(path), colour: colour || null }));
    return true;
  } catch (e) {
    showToast(t('fm.label_failed', "The label couldn't be changed: {error}", { error: e?.message || '' }), 'error');
    return false;
  }
}

export async function nameLabel(colour, name) {
  try {
    set(await api.put('/api/fs/labels/names', { colour, name: String(name || '') }));
    return true;
  } catch (e) {
    showToast(t('fm.label_failed', "The label couldn't be changed: {error}", { error: e?.message || '' }), 'error');
    return false;
  }
}

/** Marks a drawn row or card with its label: the colour for the eye, the name for a screen reader. */
export function markLabel(el, path) {
  const colour = labelOf(path);
  if (colour) {
    el.dataset.label = colour;
    el.setAttribute('aria-description', t('fm.label_is', 'Label: {name}', { name: labelName(colour) }));
  } else if (el.dataset.label) {
    delete el.dataset.label;
    el.removeAttribute('aria-description');
  }
  return colour;
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const c of children) node.append(c);
  return node;
}

function dialog(id, titleText) {
  document.getElementById(id)?.remove();
  const host = el('div', { id, className: 'smart-modal-backdrop open' });
  host.style.zIndex = '10030';
  const title = el('span', { className: 'smart-modal-title', id: `${id}-title`, textContent: titleText });
  const close = el('button', { type: 'button', className: 'win-btn close-btn' });
  close.title = t('diagnostics.close_btn', 'Close');
  close.setAttribute('aria-label', t('diagnostics.close_btn', 'Close'));
  const body = el('div', { className: 'smart-modal-body fm-label-body' });
  const win = el(
    'div',
    { className: 'smart-modal-window' },
    el('div', { className: 'smart-modal-header' }, title, el('div', { className: 'os-window-controls' }, close)),
    body
  );
  win.setAttribute('role', 'dialog');
  win.setAttribute('aria-modal', 'true');
  win.setAttribute('aria-labelledby', `${id}-title`);
  host.append(win);
  document.body.append(host);
  const shut = () => host.remove();
  close.addEventListener('click', shut);
  host.addEventListener('click', (e) => {
    if (e.target === host) shut();
  });
  host.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') shut();
  });
  return { host, body, shut };
}

/** "Label…" on a file or folder: choose a colour (or none), and name the colour if you like. */
export function openLabelPicker(item) {
  const current = labelOf(item.path);
  const { host, body, shut } = dialog('fm-label-picker', t('fm.label_title', 'Label for {name}', { name: item.name }));
  const choices = el('div', { className: 'fm-label-choices' });
  choices.setAttribute('role', 'group');
  choices.setAttribute('aria-label', t('fm.label_choose', 'Choose a colour'));
  const name = el('input', { type: 'text', className: 'tz-text-input', maxLength: 40 });
  const nameRow = el(
    'label',
    { className: 'fm-label-name', hidden: true },
    el('span', { textContent: t('fm.label_name', 'What this colour means to you (optional)') }),
    name
  );
  let chosen = current;
  const buttons = COLOURS.map((colour) => {
    const b = el('button', { type: 'button', className: 'fm-label-choice' });
    b.dataset.colour = colour;
    b.append(el('span', { className: 'fm-label-dot' }), el('span', { textContent: labelName(colour) }));
    b.setAttribute('aria-pressed', colour === current ? 'true' : 'false');
    b.addEventListener('click', () => {
      chosen = colour;
      buttons.forEach((x) => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
      nameRow.hidden = false;
      name.value = (_state && _state.names && _state.names[colour]) || '';
      name.placeholder = colourWord(colour);
    });
    return b;
  });
  choices.append(...buttons);
  const save = el('button', {
    type: 'button',
    className: 'btn-pill-toggle is-primary',
    textContent: t('fm.label_save', 'Save'),
  });
  const none = el('button', {
    type: 'button',
    className: 'btn-pill-toggle',
    textContent: t('fm.label_none', 'No label'),
    hidden: !current,
  });
  save.addEventListener('click', async () => {
    if (!chosen) return shut();
    const wanted = name.value.trim();
    const had = (_state && _state.names && _state.names[chosen]) || '';
    if (!nameRow.hidden && wanted !== had) await nameLabel(chosen, wanted);
    if (await setLabel(item.path, chosen)) shut();
    return undefined;
  });
  none.addEventListener('click', async () => {
    if (await setLabel(item.path, null)) shut();
  });
  body.append(choices, nameRow, el('div', { className: 'fm-label-actions' }, save, none));
  (buttons.find((b) => b.dataset.colour === current) || buttons[0]).focus();
  return host;
}

/** A colour in the sidebar: everything that carries it, each opening its folder. */
export function openLabelList(colour, fm) {
  const { host, body, shut } = dialog('fm-label-list', labelName(colour));
  const list = el('ul', { className: 'fm-label-list' });
  for (const path of labelledPaths(colour)) {
    const cut = path.lastIndexOf('/');
    const folder = path.slice(0, cut) || '/';
    const open = el('button', { type: 'button', className: 'fm-label-open' });
    open.append(
      el('strong', { textContent: path.slice(cut + 1) || path }),
      el('span', { className: 'kb-muted', textContent: folder })
    );
    open.addEventListener('click', () => {
      shut();
      fm.loadPath(folder);
    });
    list.append(el('li', {}, open));
  }
  if (!list.children.length)
    body.append(el('p', { className: 'kb-muted', textContent: t('fm.label_empty', 'Nothing carries this label.') }));
  else body.append(list);
  /** @type {HTMLElement | null} */ (host.querySelector('.fm-label-open, .close-btn'))?.focus();
  return host;
}

/** For tests: forget what was loaded. */
export function resetLabelsForTesting() {
  _state = null;
  _loading = null;
}
