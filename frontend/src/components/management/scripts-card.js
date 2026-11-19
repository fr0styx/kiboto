/**
 * Security: "Your own scripts" (owner's decision, 19 Nov 2026). An administrator's own scripts on a
 * timer: off until turned on, the main administrator only, every run on record. A script runs with
 * Kiboto's rights unless it is limited to one folder; the card says so before anything is saved.
 */
import { api } from '../../api.js';
import { showToast, showDangerConfirm } from '../../toast.js';
import { t } from '../../i18n.js';
import { formatDateTime } from '../../format.js';
import { weekdayNames } from '../../server-text.js';

const POLL_MS = 3000;
let _view = null;
let _editing = null; // null, 'new', or a script's id
let _showing = null; // the script whose runs are open
let _timer = null;

const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...kids.filter((k) => k !== null && k !== undefined && k !== ''));
  return node;
};

/** "Every day at 03:30", in the reader's words. */
export function scheduleSaid(script) {
  const s = script.schedule || {};
  if (s.kind === 'hourly')
    return t('scripts.sum_hourly', 'Every hour at xx:{mm}', { mm: String(s.minute || 0).padStart(2, '0') });
  if (s.kind === 'daily') return t('scripts.sum_daily', 'Every day at {time}', { time: s.at });
  if (s.kind === 'weekly')
    return t('scripts.sum_weekly', '{days} at {time}', { days: weekdayNames(s.days || []), time: s.at });
  return t('scripts.sum_manual', 'Runs only when you press Run');
}

/** How the last run ended, or that there was none. */
export function lastRunSaid(script) {
  if (script.running)
    return t('scripts.running', 'Running since {when}', { when: formatDateTime(script.running.started) });
  const r = script.last_run;
  if (!r) return t('scripts.last_never', 'Has not run yet');
  const when = formatDateTime(r.started);
  if (r.ok) return t('scripts.last_ok', 'Last run {when}: finished well', { when });
  if (r.limit_failed)
    return t('scripts.last_limit', 'Last run {when}: not started, the folder limit could not be set up', { when });
  if (r.timed_out) return t('scripts.last_timeout', 'Last run {when}: stopped at its time limit', { when });
  if (r.stopped) return t('scripts.last_stopped', 'Last run {when}: stopped by hand', { when });
  return t('scripts.last_code', 'Last run {when}: ended with an error (code {code})', { when, code: r.exit_code });
}

function scopeSaid(script) {
  return script.limit_folder
    ? t('scripts.lim_folder', 'May change files only in {folder}', { folder: script.limit_folder })
    : t('scripts.lim_all', 'Full rights');
}

function failed(err) {
  showToast(t('scripts.failed', "That didn't work: {error}", { error: err?.message || '' }), 'error');
}

async function act(fn, done) {
  try {
    const res = await fn();
    if (res && Array.isArray(res.scripts)) _view = res;
    if (done) showToast(done, 'success');
    return true;
  } catch (err) {
    failed(err);
    return false;
  } finally {
    await refresh();
    draw();
  }
}

function row(script) {
  const busy = Boolean(script.running);
  const paused = !script.enabled && (script.schedule || {}).kind !== 'manual';
  const make = (action, text, primary = false) => {
    const b = el('button', {
      type: 'button',
      className: `btn-pill-toggle${primary ? ' is-primary' : ''}`,
      textContent: text,
    });
    b.dataset.scriptAct = action;
    b.dataset.scriptId = script.id;
    return b;
  };
  const facts = [
    paused ? t('scripts.sum_paused', 'Paused: it does not run on its schedule') : scheduleSaid(script),
    scopeSaid(script),
    lastRunSaid(script),
  ];
  if (script.next_run && !paused)
    facts.push(t('scripts.next', 'Next: {when}', { when: formatDateTime(script.next_run) }));
  const item = el(
    'li',
    { className: 'scr-row' },
    el(
      'div',
      { className: 'scr-words' },
      el('strong', { textContent: script.name }),
      ...facts.map((f) => el('span', { className: 'immich-note', textContent: f }))
    ),
    el(
      'div',
      { className: 'scr-acts' },
      busy ? make('stop', t('scripts.stop', 'Stop')) : make('run', t('scripts.run', 'Run now'), true),
      make('runs', t('scripts.output', 'Last runs')),
      make('edit', t('scripts.edit', 'Edit')),
      make('delete', t('scripts.delete', 'Delete'))
    )
  );
  item.dataset.scriptRow = script.id;
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

/** The form for a new script or the one being changed. */
function form(script) {
  const s = script || { name: '', body: '', schedule: { kind: 'daily', at: '03:30' }, enabled: true, timeout_min: 30 };
  const sched = s.schedule || {};
  const name = el('input', {
    className: 'tz-select-input',
    type: 'text',
    name: 'name',
    maxLength: 60,
    value: s.name,
    required: true,
  });
  const body = el('textarea', {
    name: 'body',
    rows: 10,
    spellcheck: false,
    className: 'tz-select-input scr-body',
    value: s.body,
  });
  const kind = el('select', { name: 'kind', className: 'tz-select-input' });
  for (const [value, text] of [
    ['manual', t('scripts.when_manual', 'Only when you press Run')],
    ['hourly', t('scripts.when_hourly', 'Every hour')],
    ['daily', t('scripts.when_daily', 'Every day')],
    ['weekly', t('scripts.when_weekly', 'On some days of the week')],
  ])
    kind.append(el('option', { value, textContent: text, selected: (sched.kind || 'manual') === value }));
  const minute = el('input', {
    className: 'tz-select-input',
    type: 'number',
    name: 'minute',
    min: '0',
    max: '59',
    value: String(sched.minute || 0),
  });
  const at = el('input', { className: 'tz-select-input', type: 'time', name: 'at', value: sched.at || '03:30' });
  const days = el('div', { className: 'scr-days' });
  for (let d = 0; d < 7; d++) {
    const box = el('input', {
      type: 'checkbox',
      name: 'day',
      value: String(d),
      checked: (sched.days || []).includes(d),
    });
    days.append(el('label', { className: 'scr-day' }, box, el('span', { textContent: weekdayNames([d]) })));
  }
  const canLimit = Boolean(_view && _view.can_limit);
  const scope = el('select', { name: 'scope', className: 'tz-select-input' });
  scope.append(
    el('option', { value: 'all', textContent: t('scripts.scope_all', 'Everything Kiboto can reach (full rights)') }),
    el('option', {
      value: 'folder',
      textContent: t('scripts.scope_folder', 'Only one folder'),
      disabled: !canLimit,
      selected: Boolean(s.limit_folder),
    })
  );
  const folder = el('input', {
    className: 'tz-select-input',
    type: 'text',
    name: 'folder',
    value: s.limit_folder || '',
    placeholder: '/mnt/user/Downloads',
    spellcheck: false,
  });
  const timeout = el('input', {
    className: 'tz-select-input',
    type: 'number',
    name: 'timeout',
    min: '1',
    max: String((_view && _view.max_timeout_min) || 720),
    value: String(s.timeout_min || 30),
  });
  const enabled = el('input', { type: 'checkbox', name: 'enabled', checked: s.enabled !== false });
  const minuteField = field(t('scripts.f_minute', 'Minutes past the hour'), minute);
  const atField = field(t('scripts.f_time', 'At'), at);
  const daysField = el(
    'div',
    { className: 'ddns-field' },
    el('span', { textContent: t('scripts.f_days', 'On these days') }),
    days
  );
  const folderField = field(
    t('scripts.f_folder', 'The folder'),
    folder,
    t(
      'scripts.folder_hint',
      "The script can change files only in this folder. It can still read your other folders, and it cannot reach Kiboto's own settings, the drives themselves or your apps."
    )
  );
  const error = el('div', { className: 'ddns-error', hidden: true });
  error.setAttribute('role', 'alert');
  const f = el(
    'form',
    { className: 'ddns-form scr-form' },
    field(t('scripts.f_name', 'Name'), name),
    field(
      t('scripts.f_body', 'Script'),
      body,
      t(
        'scripts.f_body_hint',
        'A shell script. To use another language, start with a line such as #!/usr/bin/env python3.'
      )
    ),
    field(t('scripts.f_when', 'When it runs'), kind),
    minuteField,
    atField,
    daysField,
    field(
      t('scripts.f_scope', 'What it may change'),
      scope,
      canLimit ? '' : t('scripts.no_limit', 'This system cannot limit a script to a folder.')
    ),
    folderField,
    field(t('scripts.f_timeout', 'Stop it after (minutes)'), timeout),
    el(
      'label',
      { className: 'scr-day' },
      enabled,
      el('span', { textContent: t('scripts.f_enabled', 'Run it on its schedule') })
    ),
    el(
      'div',
      { className: 'ddns-actions' },
      el('button', { type: 'submit', className: 'btn-pill-toggle is-primary', textContent: t('ddns.save', 'Save') }),
      el('button', { type: 'button', className: 'btn-pill-toggle', textContent: t('scripts.cancel', 'Cancel') })
    ),
    error
  );
  f.dataset.scriptForm = script ? script.id : 'new';
  const show = () => {
    minuteField.hidden = kind.value !== 'hourly';
    atField.hidden = !['daily', 'weekly'].includes(kind.value);
    daysField.hidden = kind.value !== 'weekly';
    folderField.hidden = scope.value !== 'folder';
  };
  kind.addEventListener('change', show);
  scope.addEventListener('change', show);
  show();
  f.querySelector('button[type="button"]').addEventListener('click', () => {
    _editing = null;
    draw();
  });
  f.addEventListener('submit', async (e) => {
    e.preventDefault();
    const schedule = { kind: kind.value };
    if (kind.value === 'hourly') schedule.minute = Number(minute.value) || 0;
    if (['daily', 'weekly'].includes(kind.value)) schedule.at = at.value;
    if (kind.value === 'weekly')
      schedule.days = [...days.querySelectorAll('input:checked')].map((b) => Number(b.value));
    const payload = {
      name: name.value,
      body: body.value,
      schedule,
      enabled: enabled.checked,
      limit_folder: scope.value === 'folder' ? folder.value.trim() : '',
      timeout_min: Number(timeout.value) || 30,
    };
    try {
      _view = script
        ? await api.put(`/api/scripts/${encodeURIComponent(script.id)}`, payload)
        : await api.post('/api/scripts', payload);
      _editing = null;
      showToast(t('scripts.saved', 'Saved.'), 'success');
      draw();
    } catch (err) {
      error.textContent = err?.message || t('scripts.failed', "That didn't work: {error}", { error: '' });
      error.hidden = false;
    }
  });
  return f;
}

/** The last runs of a script, newest first, each with the end of what it printed. */
export function runsNode(script, data) {
  const box = el('div', { className: 'scr-runs' });
  box.dataset.scriptRuns = script.id;
  box.append(el('strong', { textContent: t('scripts.out_title', 'Last runs of “{name}”', { name: script.name }) }));
  const runs = (data && data.runs) || [];
  if (!runs.length)
    box.append(el('span', { className: 'immich-note', textContent: t('scripts.out_none', 'No runs on record.') }));
  for (const r of runs.slice(0, 5)) {
    const how =
      r.how === 'schedule'
        ? t('scripts.how_schedule', 'on its schedule')
        : t('scripts.how_hand', 'started by {who}', { who: r.who || '?' });
    box.append(
      el('span', {
        className: 'immich-note',
        textContent: `${lastRunSaid({ last_run: r })} (${how})`,
      })
    );
    const printed = r.output || t('scripts.out_empty', 'It printed nothing.');
    box.append(el('pre', { className: 'scr-out', textContent: printed, tabIndex: 0 }));
    if (r.output && r.output_bytes > r.output.length)
      box.append(
        el('span', {
          className: 'immich-note',
          textContent: t('scripts.out_cut', 'Only the end of what it printed is kept.'),
        })
      );
  }
  return box;
}

/** @param {boolean} [gentle] true for a look in the background: the card is left alone while a form is open */
function draw(gentle = false) {
  const box = document.getElementById('sec-scripts');
  if (!box || !_view) return;
  // a look in the background never redraws under someone who is filling in the form
  if (gentle && box.querySelector('form.scr-form')) return watch();
  const on = Boolean(_view.enabled);
  const scripts = _view.scripts || [];
  const toggle = el('button', {
    type: 'button',
    className: `btn-pill-toggle${on ? ' active' : ''}`,
    id: 'scripts-toggle',
    textContent: on ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off'),
  });
  toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
  toggle.setAttribute('aria-labelledby', 'scripts-title scripts-toggle');
  const status = on
    ? t('scripts.st_on', '{count, plural, one {On: # script} other {On: # scripts}}', { count: scripts.length })
    : t('scripts.st_off', 'Off. No script runs.');
  const head = el(
    'div',
    { className: 'scr-head' },
    el(
      'div',
      { className: 'scr-words' },
      el('h4', { id: 'scripts-title', textContent: t('scripts.title', 'Your own scripts') }),
      el('span', { className: 'immich-note', id: 'scripts-status', textContent: status })
    ),
    toggle
  );
  const parts = [
    head,
    el('p', {
      className: 'immich-note',
      textContent: t(
        'scripts.intro',
        'Run a script of your own on a timer, for example to copy a folder every night. Only the main administrator sees this, and scripts stay off until you turn them on here.'
      ),
    }),
    el('p', {
      className: 'immich-note scr-warn',
      textContent: t(
        'scripts.warn',
        "A script runs with Kiboto's rights: it can read and change every file Kiboto can, unless you limit it to one folder. A run that was due while the NAS was off is not made up for."
      ),
    }),
  ];
  if (on) {
    if (scripts.length) {
      const list = el('ul', { className: 'scr-list' });
      for (const s of scripts) {
        list.append(row(s));
        if (_editing === s.id) list.append(el('li', { className: 'scr-row' }, form(s)));
        if (_showing && _showing.id === s.id)
          list.append(el('li', { className: 'scr-row' }, runsNode(s, _showing.data)));
      }
      parts.push(list);
    } else if (_editing !== 'new') {
      parts.push(el('span', { className: 'immich-note', textContent: t('scripts.none', 'No scripts yet.') }));
    }
    if (_editing === 'new') parts.push(form(null));
    else if (scripts.length < (_view.max_scripts || 20)) {
      const add = el('button', {
        type: 'button',
        className: 'btn-pill-toggle',
        id: 'scripts-add',
        textContent: t('scripts.add', 'Add a script'),
      });
      parts.push(el('div', { className: 'ddns-actions' }, add));
    }
  }
  box.replaceChildren(...parts);
  watch();
}

/** While a run is going the card looks again every few seconds; otherwise it does not ask at all. */
function watch() {
  const going = Boolean(_view && (_view.scripts || []).some((s) => s.running));
  if (going && !_timer) _timer = setInterval(refresh, POLL_MS);
  if (!going && _timer) {
    clearInterval(_timer);
    _timer = null;
  }
}

async function refresh() {
  const box = document.getElementById('sec-scripts');
  if (!box || !box.isConnected) {
    if (_timer) clearInterval(_timer);
    _timer = null;
    return;
  }
  try {
    _view = await api.get('/api/scripts');
    if (_showing) _showing.data = await api.get(`/api/scripts/${encodeURIComponent(_showing.id)}/runs`);
  } catch {
    return; // the next look tries again
  }
  draw(true);
}

async function onClick(e) {
  const target = /** @type {HTMLElement} */ (e.target);
  if (target.id === 'scripts-toggle') {
    const turnOn = !(_view && _view.enabled);
    await act(
      () => api.put('/api/scripts/enabled', { enabled: turnOn }),
      turnOn ? t('scripts.turned_on', 'Scripts are on.') : t('scripts.turned_off', 'Scripts are off. Nothing runs.')
    );
    return;
  }
  if (target.id === 'scripts-add') {
    _editing = 'new';
    draw();
    return;
  }
  const action = target.dataset?.scriptAct;
  const id = target.dataset?.scriptId;
  const script = id && _view && (_view.scripts || []).find((s) => s.id === id);
  if (!action || !script) return;
  const path = `/api/scripts/${encodeURIComponent(id)}`;
  if (action === 'run') await act(() => api.post(`${path}/run`, {}), t('scripts.started', 'Started.'));
  else if (action === 'stop') await act(() => api.post(`${path}/stop`, {}), t('scripts.stopped', 'Stopped.'));
  else if (action === 'edit') {
    _editing = _editing === id ? null : id;
    draw();
  } else if (action === 'runs') {
    if (_showing && _showing.id === id) _showing = null;
    else {
      _showing = { id, data: null };
      try {
        _showing.data = await api.get(`${path}/runs`);
      } catch (err) {
        failed(err);
      }
    }
    draw();
  } else if (action === 'delete') {
    showDangerConfirm(
      t('scripts.del_title', 'Delete the script'),
      t('scripts.del_msg', 'Delete the script “{name}”? The record of its runs goes too.', { name: script.name }),
      async () => {
        if (_showing && _showing.id === id) _showing = null;
        if (_editing === id) _editing = null;
        await act(() => api.delete(path), t('scripts.deleted', 'Deleted.'));
      },
      null,
      { okText: t('scripts.delete', 'Delete') }
    );
  }
}

/** Draws the card under the security page's other administrator settings; false when it is not shown. */
export async function renderScriptsCard() {
  const anchor =
    document.getElementById('sec-outside-checks') ||
    document.getElementById('sec-mfa-policy') ||
    document.getElementById('sec-advisor-card');
  if (!anchor) return false;
  let box = document.getElementById('sec-scripts');
  if (!box) {
    box = el('div', { id: 'sec-scripts', className: 'sec-advisor-card' });
    anchor.after(box);
  }
  try {
    _view = await api.get('/api/scripts');
  } catch {
    box.hidden = true; // not the main administrator, or an older server
    return false;
  }
  box.hidden = false;
  if (!box.dataset.bound) {
    box.dataset.bound = '1';
    box.addEventListener('click', onClick);
  }
  draw();
  return true;
}

/** For tests: forget what was drawn. */
export function resetScriptsCardForTesting() {
  _view = null;
  _editing = null;
  _showing = null;
  if (_timer) clearInterval(_timer);
  _timer = null;
}
