/**
 * Backup: "A second NAS that can take over" (high availability, the owner's decisions of
 * 19 Nov 2026). This card pairs the two boxes: the first NAS shows a pairing key, the second one
 * is given it together with the first one's address. What the second NAS keeps in step and the
 * takeover button build on this pairing.
 */
import { api } from '../../api.js';
import { showToast } from '../../toast.js';
import { t } from '../../i18n.js';
import { formatBytes, formatDateTime } from '../../format.js';

let _view = null;
let _mode = ''; // '', 'code' (a pairing key is on screen) or 'pair' (the form)
let _code = '';

const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...kids.filter((k) => k !== null && k !== undefined && k !== ''));
  return node;
};

const WHY = {
  unreachable: ['standby.why.unreachable', 'it did not answer'],
  refused: ['standby.why.refused', 'it refused'],
  bad_message: ['standby.why.bad_message', 'its answer could not be read'],
  clock: ['standby.why.clock', 'the two boxes do not agree on the time'],
  not_paired: ['standby.why.not_paired', 'it is no longer paired with this NAS'],
};

/** How the last contact with the other NAS went, in a sentence. */
export function haReach(peer) {
  if (!peer || peer.reachable === null || peer.reachable === undefined)
    return t('standby.unchecked', 'Not checked since this NAS started.');
  if (peer.reachable)
    return t('standby.reached', 'Reached {when}.', { when: formatDateTime((peer.last_contact || 0) * 1000) });
  const why = WHY[peer.error] || WHY.unreachable;
  return t('standby.unreached', 'Not reached {when}: {why}.', {
    when: formatDateTime((peer.last_contact || 0) * 1000),
    why: t(why[0], why[1]),
  });
}

/** The copy of the first NAS's people and settings: what the second NAS keeps, or when the first was asked. */
export function haCopy(view) {
  if (view.role === 'first')
    return view.served
      ? t('standby.served', 'The second NAS last fetched people and settings {when}.', {
          when: formatDateTime(view.served * 1000),
        })
      : t('standby.served_never', 'The second NAS has not fetched people and settings yet.');
  if (view.fetching) return t('standby.fetching', 'Fetching people and settings from the first NAS…');
  const said = view.copy
    ? t(
        'standby.copy_have',
        'People and settings of {name}: a copy from {when} ({size}). It is applied only when this NAS takes over.',
        {
          name: view.copy.name || '?',
          when: formatDateTime((view.copy.made || 0) * 1000),
          size: formatBytes(view.copy.size || 0),
        }
      )
    : t('standby.copy_none', "No copy of the first NAS's people and settings yet.");
  return view.fetch_error ? `${said} ${t('standby.fetch_failed', 'The last fetch did not work.')}` : said;
}

/** Which part this NAS has, and who the other one is. */
export function haRole(view) {
  const peer = view.peer || {};
  const words = { name: peer.name || '?', address: peer.address || '' };
  return view.role === 'first'
    ? t('standby.is_first', 'This is the first NAS. The second one is {name} at {address}.', words)
    : t('standby.is_second', 'This is the second NAS. The first one is {name} at {address}.', words);
}

function failed(err) {
  if (err?.error === 'cancelled') return;
  showToast(t('standby.failed', "That didn't work: {error}", { error: err?.message || '' }), 'error');
}

function button(action, text, primary = false) {
  const b = el('button', {
    type: 'button',
    className: `btn-pill-toggle${primary ? ' is-primary' : ''}`,
    textContent: text,
  });
  b.dataset.haAct = action;
  return b;
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

function pairForm() {
  const input = (props) => el('input', { className: 'tz-select-input', type: 'text', spellcheck: false, ...props });
  const address = input({ name: 'address', placeholder: 'http://192.168.1.20:8082' });
  const code = input({ name: 'code', placeholder: 'XXXX-XXXX-XXXX-XXXX', autocomplete: 'off' });
  const mine = input({ name: 'mine', value: window.location.origin });
  const error = el('div', { className: 'ddns-error', hidden: true });
  error.setAttribute('role', 'alert');
  const f = el(
    'form',
    { className: 'ddns-form', id: 'ha-pair-form' },
    field(t('standby.f_address', "The first NAS's address"), address),
    field(
      t('standby.f_code', 'The pairing key shown on the first NAS'),
      code,
      t('standby.code_hint', 'On the first NAS, open this card and choose "This is the first NAS".')
    ),
    field(
      t('standby.f_mine', "This NAS's own address"),
      mine,
      t('standby.mine_hint', 'Where the first NAS reaches this one: its number address on your home network.')
    ),
    el(
      'div',
      { className: 'ddns-actions' },
      el('button', { type: 'submit', className: 'btn-pill-toggle is-primary', textContent: t('standby.pair', 'Pair') }),
      button('cancel', t('standby.cancel', 'Cancel'))
    ),
    error
  );
  f.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      _view = await api.post('/api/ha/pair', {
        address: address.value.trim(),
        code: code.value.trim(),
        my_address: mine.value.trim(),
      }); // the server asks to confirm
      _mode = '';
      showToast(t('standby.paired_toast', 'Paired. This is the second NAS now.'), 'success');
      draw();
    } catch (err) {
      if (err?.error === 'cancelled') return;
      error.textContent = err?.message || t('standby.failed', "That didn't work: {error}", { error: '' });
      error.hidden = false;
    }
  });
  return f;
}

function draw() {
  const card = document.getElementById('ha-card');
  if (!card || !_view) return;
  const parts = [
    el('h3', {
      className: 'offsite-title',
      id: 'ha-title',
      textContent: t('standby.title', 'A second NAS that can take over'),
    }),
    el('p', {
      className: 'offsite-note',
      textContent: t(
        'standby.intro',
        'Two Kiboto boxes at home: the first is the one you use, the second keeps a copy of chosen folders, people and settings and takes over when you say so. The two are paired with a key that is shown once; everything they send each other is encrypted, also without Tailscale.'
      ),
    }),
  ];
  if (_view.role) {
    parts.push(
      el('p', { className: 'immich-note', id: 'ha-role', textContent: haRole(_view) }),
      el('p', { className: 'immich-note', id: 'ha-reach', textContent: haReach(_view.peer) }),
      el('p', { className: 'immich-note', id: 'ha-copy', textContent: haCopy(_view) }),
      el(
        'div',
        { className: 'ddns-actions' },
        button('check', t('standby.check', 'Check now')),
        _view.role === 'second' && !_view.fetching ? button('fetch', t('standby.fetch', 'Fetch now')) : null,
        button('unpair', t('standby.unpair', 'Unpair'))
      ),
      el('p', {
        className: 'immich-note',
        textContent: t(
          'standby.next_note',
          'Pairing and the copy of people and settings work. The chosen folders and the takeover button come with the next updates and will show here.'
        ),
      })
    );
  } else if (_mode === 'code') {
    parts.push(
      el('p', {
        className: 'immich-note',
        textContent: t('standby.code_title', 'The pairing key. Type it into the second NAS:'),
      }),
      el('code', { className: 'ha-code', id: 'ha-code', textContent: _code }),
      el('p', {
        className: 'immich-note',
        textContent: t('standby.code_note', 'It is good for 10 minutes and for one pairing, and it is shown only now.'),
      }),
      el('div', { className: 'ddns-actions' }, button('cancel', t('standby.done', 'Done')))
    );
  } else if (_mode === 'pair') {
    parts.push(pairForm());
  } else {
    parts.push(
      el(
        'div',
        { className: 'ddns-actions' },
        button('first', t('standby.first_btn', 'This is the first NAS: show a pairing key')),
        button('second', t('standby.second_btn', 'This is the second NAS: pair with the first'))
      )
    );
  }
  card.replaceChildren(...parts);
}

async function onClick(e) {
  const action = /** @type {HTMLElement} */ (e.target).dataset?.haAct;
  if (!action) return;
  try {
    if (action === 'first') {
      _code = (await api.post('/api/ha/code', {})).code;
      _mode = 'code';
    } else if (action === 'second') {
      _mode = 'pair';
    } else if (action === 'cancel') {
      _mode = '';
      _code = '';
      _view = await api.get('/api/ha'); // the first NAS: the second one may have paired meanwhile
    } else if (action === 'check') {
      _view = await api.post('/api/ha/check', {});
    } else if (action === 'fetch') {
      _view = await api.post('/api/ha/fetch', {});
      showToast(t('standby.fetch_started', 'Fetching. The card shows the copy when it has arrived.'), 'success');
    } else if (action === 'unpair') {
      _view = await api.delete('/api/ha'); // the server asks to confirm
      showToast(t('standby.unpaired_toast', 'Unpaired.'), 'success');
    }
  } catch (err) {
    failed(err);
  }
  draw();
}

/** Draws the card on the Backup page, after the copies outside this Kiboto; false when it is not shown. */
export async function renderHaCard() {
  const after = document.querySelector('.offsite-card:not(.ha-card)');
  if (!after) return false;
  let card = document.getElementById('ha-card');
  if (!card) {
    card = el('section', { id: 'ha-card', className: 'drawer-card offsite-card ha-card' });
    card.setAttribute('aria-labelledby', 'ha-title');
    after.insertAdjacentElement('afterend', card);
  }
  try {
    _view = await api.get('/api/ha');
  } catch {
    card.hidden = true; // not someone who may change the system, or an older server
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
export function resetHaCardForTesting() {
  _view = null;
  _mode = '';
  _code = '';
}
