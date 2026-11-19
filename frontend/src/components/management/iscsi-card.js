/**
 * Network → services: "Disks for other computers (iSCSI)" (owner's decision, 19 Nov 2026). Off until
 * turned on. A disk is a file in one of the NAS's folders that another computer uses as a drive of
 * its own; each has a user name and a password, which is sent once and never comes back.
 */
import { api } from '../../api.js';
import { showToast } from '../../toast.js';
import { t } from '../../i18n.js';
import { formatBytes } from '../../format.js';

let _view = null;
let _editing = null; // null, 'new', or a disk's id

const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...kids.filter((k) => k !== null && k !== undefined && k !== ''));
  return node;
};

/** The status line: off, answering, waiting for a first disk, or not running. */
export function iscsiStatus(v) {
  if (!v || !v.enabled) return t('iscsi.st_off', 'Off.');
  if (!(v.disks || []).length) return t('iscsi.st_nodisk', 'On. Add a disk to start the service.');
  if (v.running) return t('iscsi.st_on', 'Answers on port {port}.', { port: v.port });
  if (v.why === 'engine')
    return t('iscsi.st_engine', 'Not running: Kiboto cannot reach the app engine on this system to start the service.');
  if (v.why === 'folder')
    return t('iscsi.st_folder', "Not running: a disk's folder is not one the service can be given.");
  return t('iscsi.st_down', 'Not running. Port {port} may be in use by another program on this NAS.', { port: v.port });
}

function failed(err) {
  if (err?.error === 'cancelled') return;
  showToast(t('iscsi.failed', "That didn't work: {error}", { error: err?.message || '' }), 'error');
}

function row(d) {
  const who =
    t('iscsi.row_who', 'Signs in as {user}', { user: d.user }) +
    (d.allow ? `, ${t('iscsi.row_only', 'only from {allow}', { allow: d.allow })}` : '');
  const facts = [
    t('iscsi.row_size', '{size} GB, {used} written so far', { size: d.size_gb, used: formatBytes(d.used_bytes || 0) }),
    who,
    t('iscsi.row_iqn', 'Its name for the other computer: {iqn}', { iqn: d.iqn }),
  ];
  if (!d.file_there) facts.push(t('iscsi.row_missing', 'Its file is not there: {file}', { file: d.file }));
  const button = (action, text) => {
    const b = el('button', { type: 'button', className: 'btn-pill-toggle', textContent: text });
    b.dataset.iscsiAct = action;
    b.dataset.iscsiId = d.id;
    return b;
  };
  const item = el(
    'li',
    { className: 'scr-row' },
    el(
      'div',
      { className: 'scr-words' },
      el('strong', { textContent: d.name }),
      ...facts.map((f) => el('span', { className: 'immich-note', textContent: f }))
    ),
    el(
      'div',
      { className: 'scr-acts' },
      button('edit', t('iscsi.edit', 'Edit')),
      button('remove', t('iscsi.remove', 'Remove'))
    )
  );
  item.dataset.iscsiRow = d.id;
  return item;
}

function field(labelText, control, hint = '') {
  return el(
    'label',
    { className: 'ddns-field' },
    el('span', { textContent: labelText }),
    control,
    hint ? el('span', { className: 'immich-note', textContent: hint }) : null
  );
}

function form(disk) {
  const d = disk || { name: '', size_gb: 100, folder: '', user: '', allow: '' };
  const input = (props) => el('input', { className: 'tz-select-input', ...props });
  const name = input({
    type: 'text',
    name: 'name',
    value: d.name,
    maxLength: 31,
    spellcheck: false,
    disabled: Boolean(disk),
  });
  const size = input({
    type: 'number',
    name: 'size',
    min: String(d.size_gb && disk ? d.size_gb : 1),
    max: String((_view && _view.max_gb) || 65536),
    value: String(d.size_gb),
  });
  const folder = input({
    type: 'text',
    name: 'folder',
    value: d.folder,
    placeholder: '/mnt/user/iscsi',
    spellcheck: false,
    disabled: Boolean(disk),
  });
  const user = input({
    type: 'text',
    name: 'user',
    value: d.user,
    maxLength: 32,
    spellcheck: false,
    autocomplete: 'off',
  });
  const secret = input({
    type: 'password',
    name: 'secret',
    minLength: 12,
    maxLength: 16,
    autocomplete: 'new-password',
    placeholder: disk ? t('iscsi.secret_saved', 'Saved; type a new one to change it') : '',
  });
  const allow = input({
    type: 'text',
    name: 'allow',
    value: d.allow || '',
    placeholder: '192.168.1.20',
    spellcheck: false,
  });
  const error = el('div', { className: 'ddns-error', hidden: true });
  error.setAttribute('role', 'alert');
  const f = el(
    'form',
    { className: 'ddns-form scr-form' },
    field(t('iscsi.f_name', 'Name (small letters, digits, hyphens)'), name),
    field(t('iscsi.f_size', 'Size (GB)'), size),
    field(
      t('iscsi.f_folder', 'Folder for its file'),
      folder,
      t(
        'iscsi.folder_hint',
        'The disk is one file in this folder. It takes no space until the other computer writes to it.'
      )
    ),
    field(t('iscsi.f_user', 'User name'), user),
    field(t('iscsi.f_secret', 'Password (12 to 16 characters)'), secret),
    field(
      t('iscsi.f_allow', 'Only from this address (optional)'),
      allow,
      t('iscsi.allow_hint', 'For example 192.168.1.20. Empty: any computer on the network that has the password.')
    ),
    el('p', {
      className: 'immich-note',
      textContent: t(
        'iscsi.save_note',
        'Saving restarts the service: a computer that is using a disk is cut off for a moment.'
      ),
    }),
    el(
      'div',
      { className: 'ddns-actions' },
      el('button', { type: 'submit', className: 'btn-pill-toggle is-primary', textContent: t('ddns.save', 'Save') }),
      el('button', { type: 'button', className: 'btn-pill-toggle', textContent: t('iscsi.cancel', 'Cancel') })
    ),
    error
  );
  f.dataset.iscsiForm = disk ? disk.id : 'new';
  f.querySelector('button[type="button"]').addEventListener('click', () => {
    _editing = null;
    draw();
  });
  f.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      name: name.value.trim(),
      size_gb: Number(size.value) || 0,
      folder: folder.value.trim(),
      user: user.value.trim(),
      secret: secret.value,
      allow: allow.value.trim(),
    };
    try {
      _view = disk
        ? await api.put(`/api/iscsi/disks/${encodeURIComponent(disk.id)}`, payload)
        : await api.post('/api/iscsi/disks', payload);
      _editing = null;
      showToast(t('iscsi.saved', 'Saved.'), 'success');
      draw();
    } catch (err) {
      if (err?.error === 'cancelled') return;
      error.textContent = err?.message || t('iscsi.failed', "That didn't work: {error}", { error: '' });
      error.hidden = false;
    }
  });
  return f;
}

function draw() {
  const card = document.getElementById('iscsi-card');
  if (!card || !_view) return;
  const on = Boolean(_view.enabled);
  const disks = _view.disks || [];
  const toggle = el('button', {
    type: 'button',
    className: `btn-pill-toggle${on ? ' active' : ''}`,
    id: 'iscsi-toggle',
    textContent: on ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off'),
  });
  toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
  toggle.setAttribute('aria-labelledby', 'iscsi-title iscsi-toggle');
  const parts = [
    el(
      'div',
      { className: 'scr-head' },
      el(
        'div',
        { className: 'scr-words' },
        el('div', {
          className: 'nsv-fs13-bold-strong',
          id: 'iscsi-title',
          textContent: t('iscsi.title', 'Disks for other computers (iSCSI)'),
        }),
        el('span', { className: 'immich-note', id: 'iscsi-status', textContent: iscsiStatus(_view) })
      ),
      toggle
    ),
    el('p', {
      className: 'immich-note',
      textContent: t(
        'iscsi.intro',
        "Lends another computer a disk over the network: it uses a file in one of your folders as if it were a drive of its own. For a virtualisation host, a PC's games library or a backup program that wants a disk. Off until you turn it on."
      ),
    }),
  ];
  if (on) {
    if (disks.length) {
      const list = el('ul', { className: 'scr-list' });
      for (const d of disks) {
        list.append(row(d));
        if (_editing === d.id) list.append(el('li', { className: 'scr-row' }, form(d)));
      }
      parts.push(
        list,
        el('p', {
          className: 'immich-note',
          textContent: t(
            'iscsi.connect_hint',
            "On the other computer, connect to this NAS's address on port {port} and sign in with the disk's user name and password.",
            { port: _view.port }
          ),
        })
      );
    } else if (_editing !== 'new') {
      parts.push(el('span', { className: 'immich-note', textContent: t('iscsi.none', 'No disks yet.') }));
    }
    if (_editing === 'new') parts.push(form(null));
    else if (disks.length < (_view.max_disks || 8)) {
      const add = el('button', {
        type: 'button',
        className: 'btn-pill-toggle',
        id: 'iscsi-add',
        textContent: t('iscsi.add', 'Add a disk'),
      });
      parts.push(el('div', { className: 'ddns-actions' }, add));
    }
  }
  card.replaceChildren(...parts);
}

async function onClick(e) {
  const target = /** @type {HTMLElement} */ (e.target);
  if (target.id === 'iscsi-toggle') {
    const turnOn = !(_view && _view.enabled);
    try {
      _view = await api.put('/api/iscsi/enabled', { enabled: turnOn });
      showToast(
        turnOn ? t('iscsi.turned_on', 'iSCSI is on.') : t('iscsi.turned_off', 'iSCSI is off. No disk is offered.'),
        'success'
      );
    } catch (err) {
      failed(err);
    }
    draw();
    return;
  }
  if (target.id === 'iscsi-add') {
    _editing = 'new';
    draw();
    return;
  }
  const action = target.dataset?.iscsiAct;
  const id = target.dataset?.iscsiId;
  if (!action || !id) return;
  if (action === 'edit') {
    _editing = _editing === id ? null : id;
    draw();
  } else if (action === 'remove') {
    try {
      _view = await api.delete(`/api/iscsi/disks/${encodeURIComponent(id)}`); // the server asks to confirm
      if (_editing === id) _editing = null;
      showToast(t('iscsi.removed', 'Removed from the list. Its file is still in its folder.'), 'success');
    } catch (err) {
      failed(err);
    }
    draw();
  }
}

/** Draws the card among the network services; false when it is not shown. */
export async function renderIscsiCard() {
  const grid = document.getElementById('network-services-grid');
  if (!grid) return false;
  let card = document.getElementById('iscsi-card');
  if (!card) {
    card = el('div', { id: 'iscsi-card', className: 'nsv-col-box' });
    grid.appendChild(card);
  }
  try {
    _view = await api.get('/api/iscsi');
  } catch {
    card.hidden = true; // not someone who manages the storage, or an older server
    return false;
  }
  card.hidden = false;
  if (!card.dataset.bound) {
    card.dataset.bound = '1';
    card.addEventListener('click', onClick);
  }
  draw();
  return true;
}

/** For tests: forget what was drawn. */
export function resetIscsiCardForTesting() {
  _view = null;
  _editing = null;
}
