/**
 * Backup: "A second NAS that can take over" (high availability, the owner's decisions of
 * 19 Nov 2026). This card pairs the two boxes: the first NAS shows a pairing key, the second one
 * is given it together with the first one's address. The second NAS keeps a copy of people,
 * settings and chosen folders, and takes over by a button here; the first NAS then holds its name
 * back until it is taken back on it.
 */
import { api } from '../../api.js';
import { showToast } from '../../toast.js';
import { t } from '../../i18n.js';
import { formatBytes, formatDateTime } from '../../format.js';

let _view = null;
let _mode = ''; // '', 'code' (a pairing key is on screen) or 'pair' (the form)
let _folders = null; // on the second NAS: the first one's shared folders, once asked
let _code = '';
let _answers = false; // the second NAS asked to take over, and the first one still answers
const _bring = new Set(); // what else the person ticked to come along at the takeover
let _unreached = false; // the first NAS asked for its name back, and the second one did not answer

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

const FOLDER_WHY = {
  full: ['standby.fw_full', 'this NAS is full'],
  make_folder: ['standby.fw_make', 'make a shared folder of that name on this NAS first'],
  no_folder: ['standby.fw_gone', 'the first NAS no longer has it'],
  unreachable: ['standby.fw_unreachable', 'the first NAS did not answer'],
};

/** How the last fetch of one folder went, in a sentence or two. */
export function haFolderLine(name, last) {
  if (!last) return t('standby.f_never', '{name}: not fetched yet.', { name });
  const when = formatDateTime((last.at || 0) * 1000);
  if (last.why && last.why !== 'full' && !last.fetched && !last.same) {
    const why = FOLDER_WHY[last.why] || ['standby.fw_other', 'it did not work'];
    return t('standby.f_failed', '{name}: not fetched {when}: {why}.', { name, when, why: t(why[0], why[1]) });
  }
  const said = [
    t(
      'standby.f_last',
      '{name}, fetched {when}: {fetched, plural, one {# file new or changed} other {# files new or changed}} ({size}), {same, plural, one {# unchanged} other {# unchanged}}.',
      { name, when, fetched: last.fetched || 0, size: formatBytes(last.bytes || 0), same: last.same || 0 }
    ),
  ];
  if (last.removed)
    said.push(
      t(
        'standby.f_removed',
        '{count, plural, one {# file is gone on the first NAS and was put away here} other {# files are gone on the first NAS and were put away here}}.',
        {
          count: last.removed,
        }
      )
    );
  if (last.kept_yours)
    said.push(
      t(
        'standby.f_kept',
        "{count, plural, one {# file of this NAS's own was left alone} other {# files of this NAS's own were left alone}}.",
        {
          count: last.kept_yours,
        }
      )
    );
  if ((last.errors || []).length)
    said.push(
      t(
        'standby.f_errors',
        '{count, plural, one {# file could not be fetched} other {# files could not be fetched}}.',
        {
          count: last.errors.length,
        }
      )
    );
  if (last.why === 'full') said.push(t('standby.f_full', 'It stopped because this NAS is full.'));
  return said.join(' ');
}

function foldersPart() {
  const chosen = new Set(_view.folders || []);
  const names = [...new Set([...((_folders && _folders.available) || []), ...chosen])].sort();
  const box = el('div', { className: 'ha-folders', id: 'ha-folders' });
  box.append(
    el('div', { className: 'nsv-fs13-bold-strong', textContent: t('standby.folders_title', 'Folders kept in step') }),
    el('p', {
      className: 'immich-note',
      textContent: t(
        'standby.folders_hint',
        'The folders you tick are fetched from the first NAS every night into shared folders of the same names on this NAS. A file deleted on the first NAS is kept here for {days, plural, one {# day} other {# days}} in a hidden folder. Fetching wakes the drives of both boxes.',
        { days: _view.keep_removed_days || 30 }
      ),
    })
  );
  if (_folders && _folders.available === null)
    box.append(
      el('p', {
        className: 'immich-note',
        id: 'ha-folders-unasked',
        textContent: t('standby.folders_unasked', 'The first NAS could not be asked for its folders just now.'),
      })
    );
  const list = el('div', { className: 'ha-folder-list' });
  for (const name of names) {
    const check = el('input', { type: 'checkbox', checked: chosen.has(name) });
    check.dataset.haFolder = name;
    list.append(el('label', { className: 'ha-folder' }, check, el('span', { textContent: name })));
  }
  box.append(list);
  if (names.length)
    box.append(
      el('div', { className: 'ddns-actions' }, button('folders', t('standby.folders_save', 'Save the choice')))
    );
  for (const name of [...chosen].sort())
    box.append(
      el('p', { className: 'immich-note', textContent: haFolderLine(name, (_view.folders_last || {})[name]) })
    );
  return box;
}

/** Which part this NAS has, and who the other one is. */
export function haRole(view) {
  const peer = view.peer || {};
  const words = { name: peer.name || '?', address: peer.address || '' };
  if (view.role === 'took_over') {
    const took = view.took_over || {};
    const said = t('standby.took_over', 'This NAS took over from {name} on {when}.', {
      name: took.from || words.name,
      when: formatDateTime((took.at || 0) * 1000),
    });
    const parts = [said];
    if (took.name) parts.push(t('standby.took_over_name', 'It answers to {host}.', { host: `${took.name}.local` }));
    const b = took.brought || {};
    if (b.jobs || b.offsite || b.jobs_left || b.offsite_left)
      parts.push(
        t(
          'standby.brought_backups',
          '{came, plural, one {# backup came along, switched off} other {# backups came along, switched off}}; {left, plural, one {# stayed behind} other {# stayed behind}}.',
          { came: (b.jobs || 0) + (b.offsite || 0), left: (b.jobs_left || 0) + (b.offsite_left || 0) }
        )
      );
    return parts.join(' ');
  }
  return view.role === 'first'
    ? t('standby.is_first', 'This is the first NAS. The second one is {name} at {address}.', words)
    : t('standby.is_second', 'This is the second NAS. The first one is {name} at {address}.', words);
}

/** On the second NAS: what taking over does, and the button; a second button once the first NAS answered. */
function takeoverPart() {
  const box = el('div', { className: 'ha-folders', id: 'ha-takeover' });
  box.append(
    el('div', { className: 'nsv-fs13-bold-strong', textContent: t('standby.takeover_title', 'Taking over') }),
    el('p', {
      className: 'immich-note',
      textContent: _view.copy
        ? t(
            'standby.takeover_note',
            'When the first NAS is broken or gone, this NAS takes its people and their sign-in, who may open the folders kept here, and its name. It keeps its own network address, apps and backups. It restarts, and you sign in with an account of the first NAS.'
          )
        : t('standby.takeover_no_copy', 'Taking over needs the copy of people and settings. Fetch it first.'),
    })
  );
  if (_view.copy) {
    // a choice, because a backup acts on its own once it runs: it arrives switched off
    const holds = _view.copy.holds || {};
    const tick = el('input', { type: 'checkbox', id: 'ha-bring-backups', checked: _bring.has('backups') });
    tick.dataset.haBring = 'backups';
    tick.addEventListener('change', () => (tick.checked ? _bring.add('backups') : _bring.delete('backups')));
    box.append(
      el(
        'label',
        { className: 'ha-folder' },
        tick,
        el('span', { textContent: t('standby.bring_backups', "Also bring the first NAS's backups, switched off") })
      ),
      el('p', {
        className: 'immich-note',
        id: 'ha-bring-note',
        textContent: `${t(
          'standby.bring_backups_note',
          'A backup comes along when its folder is one of the folders kept here, with its password and its cloud sign-in. You turn each one on under Backup after a look. A backup onto a drive of the first NAS stays behind.'
        )}${
          holds.backup_jobs || holds.offsite
            ? ` ${t('standby.bring_backups_count', 'The copy holds {jobs, plural, one {# copy job} other {# copy jobs}} and {offsite, plural, one {# off-site backup} other {# off-site backups}}.', { jobs: holds.backup_jobs || 0, offsite: holds.offsite || 0 })}`
            : ''
        }`,
      })
    );
  }
  if (_answers)
    box.append(
      el('p', {
        className: 'immich-note',
        id: 'ha-answers',
        textContent: t(
          'standby.answers_note',
          'The first NAS still answers, so two boxes would answer to one name. Turn the first NAS off and try again, or take over anyway.'
        ),
      })
    );
  if (_view.copy)
    box.append(
      el(
        'div',
        { className: 'ddns-actions' },
        button('takeover', t('standby.takeover_btn', 'Take over now')),
        _answers ? button('takeover_anyway', t('standby.takeover_anyway', 'Take over although it answers')) : null
      )
    );
  return box;
}

/** On a first NAS whose second one took over: that it is silent, and the way back. */
function heldPart() {
  const box = el('div', { className: 'ha-folders', id: 'ha-held' });
  box.append(
    el('p', {
      className: 'immich-note',
      textContent: t(
        'standby.held',
        'The second NAS took over ({when}). This NAS does not answer to its name until you take the name back here. Files and people changed on the second NAS meanwhile are not copied back by themselves.',
        { when: formatDateTime(((_view.stood_down || {}).at || 0) * 1000) }
      ),
    })
  );
  if (_unreached)
    box.append(
      el('p', {
        className: 'immich-note',
        id: 'ha-unreached',
        textContent: t(
          'standby.unreached_note',
          'The second NAS did not answer, so it may still answer to the name. Turn it off and try again, or take the name back anyway.'
        ),
      })
    );
  box.append(
    el(
      'div',
      { className: 'ddns-actions' },
      button('takeback', t('standby.take_back', 'Take the name back')),
      _unreached ? button('takeback_anyway', t('standby.take_back_anyway', 'Take it back anyway')) : null
    )
  );
  return box;
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
      // a box that took over has applied the copy: there is nothing more to say about it
      _view.role === 'took_over'
        ? null
        : el('p', { className: 'immich-note', id: 'ha-copy', textContent: haCopy(_view) }),
      _view.role === 'second' ? foldersPart() : null,
      _view.role === 'first' && _view.stood_down ? heldPart() : null,
      el(
        'div',
        { className: 'ddns-actions' },
        button('check', t('standby.check', 'Check now')),
        _view.role === 'second' && !_view.fetching ? button('fetch', t('standby.fetch', 'Fetch now')) : null,
        button('unpair', t('standby.unpair', 'Unpair'))
      ),
      _view.role === 'second' ? takeoverPart() : null
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
    } else if (action === 'folders') {
      const names = [...document.querySelectorAll('#ha-card input[data-ha-folder]')]
        .filter((c) => /** @type {HTMLInputElement} */ (c).checked)
        .map((c) => /** @type {HTMLElement} */ (c).dataset.haFolder);
      _view = await api.put('/api/ha/folders', { names }); // the server asks to confirm
      showToast(t('standby.folders_saved', 'Saved. The folders are fetched now, and every night.'), 'success');
    } else if (action === 'fetch') {
      _view = await api.post('/api/ha/fetch', {});
      showToast(t('standby.fetch_started', 'Fetching. The card shows the copy when it has arrived.'), 'success');
    } else if (action === 'takeover' || action === 'takeover_anyway') {
      // the server asks to confirm; it refuses while the first NAS answers, unless told it is known
      _view = await api.post('/api/ha/takeover', {
        even_if_answering: action === 'takeover_anyway',
        bring: [..._bring],
      });
      _answers = false;
      _bring.clear();
      showToast(
        _view.restarting
          ? t(
              'standby.takeover_started',
              'Taking over. This NAS restarts now; sign in with an account of the first NAS.'
            )
          : t(
              'standby.takeover_restart',
              'Taking over. Restart Kiboto to finish, then sign in with an account of the first NAS.'
            ),
        'success'
      );
    } else if (action === 'takeback' || action === 'takeback_anyway') {
      _view = await api.post('/api/ha/take-back', { even_if_unreachable: action === 'takeback_anyway' });
      _unreached = false;
      showToast(t('standby.took_back', 'This NAS answers to its name again.'), 'success');
    } else if (action === 'unpair') {
      _view = await api.delete('/api/ha'); // the server asks to confirm
      showToast(t('standby.unpaired_toast', 'Unpaired.'), 'success');
    }
  } catch (err) {
    // two refusals are questions, not failures: the card then offers the second button
    if (err?.error === 'ha_first_answers') _answers = true;
    else if (err?.error === 'ha_second_unreachable') _unreached = true;
    else failed(err);
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
  if (_view.role === 'second') {
    // the first NAS's folders are asked for after the card is up: it may take a moment, or not answer
    try {
      _folders = await api.get('/api/ha/folders');
    } catch {
      _folders = { available: null };
    }
    draw();
  }
  return true;
}

/** For tests: forget what was drawn. */
export function resetHaCardForTesting() {
  _view = null;
  _mode = '';
  _code = '';
  _folders = null;
  _answers = false;
  _unreached = false;
  _bring.clear();
}
