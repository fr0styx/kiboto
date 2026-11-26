/**
 * Shared folders: "Old files move to the slower drives" (data tiering, owner's decisions 19 Nov 2026).
 * Per shared folder, off until turned on. Kiboto watches which files are opened; a file nobody
 * opened or changed for the folder's days moves at night, and stays where it moved to.
 */
import { api } from '../api.js';
import { showToast } from '../toast.js';
import { t } from '../i18n.js';
import { editionLine } from '../edition-line.js';
import { formatBytes, formatDate, formatDateTime } from '../format.js';

let _view = null;

const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...kids.filter((k) => k !== null && k !== undefined && k !== ''));
  return node;
};

const WHY = {
  not_yet: ['srv.os_not_yet', 'This is not available on Kiboto OS yet.'],
  unraid_moves_all: [
    'tier.why.unraid_moves_all',
    "Unraid already moves all of this folder's files to the array each night.",
  ],
  unraid_moves_back: [
    'tier.why.unraid_moves_back',
    "Unraid moves this folder's files back to the fast pool each night.",
  ],
  not_on_fast: ['tier.why.not_on_fast', 'This folder is not kept on a fast pool.'],
  exclusive: [
    'tier.why.exclusive',
    'Unraid shows this folder straight from its pool (exclusive access), so files on the array would not appear in it.',
  ],
  fast_not_visible: ['tier.why.fast_not_visible', "Kiboto cannot see this folder's fast pool."],
  no_slow_drive: ['tier.why.no_slow_drive', 'The array has no drive this folder may use.'],
  no_merged_folder: [
    'tier.why.no_merged_folder',
    'On this system a folder lives on one pool, so there is no slower place to move its files to.',
  ],
  one_pool: ['tier.why.one_pool', 'There is no second pool its old files could move to.'],
  nfs: ['tier.why.nfs', 'This folder is shared over NFS; a folder on two pools is not offered over NFS yet.'],
  own_mount: [
    'tier.why.own_mount',
    'This folder is mounted on its own (a ZFS dataset, for example); that is not supported yet.',
  ],
  needs_shared_mounts: [
    'tier.why.needs_shared_mounts',
    "Kiboto's install file has to share mounts between its containers first. The guide (docs/TIERING.md) shows the two lines to change.",
  ],
  no_merge_tool: ['tier.why.no_merge_tool', 'This system cannot show two pools as one folder.'],
};

/** The name of the pool a merged folder's old files go to. */
function slowName(f) {
  const pool = (f.slow_choices || []).find((p) => p.id === f.slow_pool);
  return pool ? pool.name : f.slow_pool;
}

/** Why moving old files does not fit a folder, in words. */
export function tieringWhy(why) {
  const known = WHY[why] || WHY.not_on_fast;
  return t(known[0], known[1]);
}

/** How the last run went, in one or two sentences. */
export function tieringLastRun(run) {
  const when = formatDateTime(run.ended * 1000);
  const count = run.moved || 0;
  const said = [];
  if (run.why === 'full')
    said.push(
      t(
        'tier.last_full',
        'Last run {when}: the slower drives are full, so it stopped. {count, plural, one {# file} other {# files}} moved.',
        { when, count }
      )
    );
  else if (run.why === 'too_long')
    said.push(
      t('tier.last_long', 'Last run {when}: it took too long and was stopped. The rest follows on the next night.', {
        when,
      })
    );
  else if (run.why === 'not_watching')
    said.push(
      t('tier.last_blind', 'Last run {when}: nothing moved, because Kiboto was not seeing which files are opened.', {
        when,
      })
    );
  else if (run.why === 'not_mounted')
    said.push(
      t(
        'tier.last_unmounted',
        'Last run {when}: nothing moved, because the two pools were not shown as one at that time.',
        { when }
      )
    );
  else if (run.why === 'no_slow_drive')
    said.push(
      t(
        'tier.last_nodrive',
        'Last run {when}: nothing moved, because no drive of the array has room for this folder.',
        {
          when,
        }
      )
    );
  else if (run.why)
    said.push(
      t('tier.last_failed', 'Last run {when}: Kiboto could not start the program that moves the files.', { when })
    );
  else if (count)
    said.push(
      t('tier.last_moved', 'Last run {when}: {count, plural, one {# file} other {# files}} moved ({size}).', {
        when,
        count,
        size: formatBytes(run.bytes || 0),
      })
    );
  else if (run.chosen) said.push(t('tier.last_stayed', 'Last run {when}: nothing moved.', { when }));
  else said.push(t('tier.last_none', 'Last run {when}: no file was old enough.', { when }));
  const open = (run.counts && run.counts.in_use) || 0;
  if (open)
    said.push(
      t('tier.last_open', '{count, plural, one {# file was open and stayed} other {# files were open and stayed}}.', {
        count: open,
      })
    );
  const failed = (run.errors || []).length;
  if (failed)
    said.push(
      t('tier.last_errors', '{count, plural, one {# file} other {# files}} could not be moved.', { count: failed })
    );
  if (run.more) said.push(t('tier.more', 'More files are old than one night moves; the rest follows.'));
  return said.join(' ');
}

/** A folder's status line. */
export function tieringStatus(f, view) {
  if (f.kind === 'merged' && f.slow_pool && f.mounted === false)
    return t(
      'tier.st_unmounted',
      'The two pools are not shown as one right now: the files on {pool} are missing from the folder until that is running again. Nothing is lost.',
      { pool: slowName(f) }
    );
  if (!f.enabled && f.kind === 'merged' && f.slow_pool)
    return t('tier.st_off_merged', 'Off. Its old files stay on {pool} and keep showing in the folder.', {
      pool: slowName(f),
    });
  if (!f.enabled) return t('tier.st_off', 'Off.');
  if (!f.watching)
    return t('tier.st_blind', 'On, but Kiboto cannot see which files are opened on this system, so nothing moves.');
  if (f.learning)
    return t('tier.st_learning', 'Watching which files are opened. Nothing moves before {date}.', {
      date: formatDate(f.learning_until * 1000),
    });
  if (f.last_run && f.last_run.ended) return tieringLastRun(f.last_run);
  return t('tier.st_ready', 'On. Files not opened for {days, plural, one {# day} other {# days}} move at {time}.', {
    days: f.days,
    time: view.run_at,
  });
}

function failed(err) {
  if (err?.error === 'cancelled') return;
  showToast(t('tier.failed', "That didn't work: {error}", { error: err?.message || '' }), 'error');
}

function row(f) {
  const toggle = el('button', {
    type: 'button',
    className: `btn-pill-toggle${f.enabled ? ' active' : ''}`,
    textContent: f.enabled ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off'),
  });
  toggle.dataset.tierAct = 'toggle';
  toggle.dataset.tierName = f.name;
  toggle.setAttribute('aria-pressed', f.enabled ? 'true' : 'false');
  toggle.setAttribute(
    'aria-label',
    `${f.name}: ${f.enabled ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off')}`
  );
  const days = el('input', {
    type: 'number',
    className: 'tz-select-input tier-days',
    min: String(_view.min_days || 7),
    max: String(_view.max_days || 3650),
    value: String(f.days || _view.default_days || 90),
  });
  days.dataset.tierDays = f.name;
  const acts = [
    el(
      'label',
      { className: 'tier-days-label' },
      el('span', { textContent: t('tier.days_label', 'Days not opened') }),
      days
    ),
  ];
  if (f.kind === 'merged' && !f.slow_pool) {
    // on one of Kiboto's own pools: which pool takes the old files is chosen once, when it is turned on
    const slow = el('select', { className: 'tz-select-input tier-slow' });
    slow.dataset.tierSlow = f.name;
    for (const p of f.slow_choices || [])
      slow.append(
        el('option', {
          value: p.id,
          textContent: t('tier.slow_option', '{name} ({free} free)', {
            name: p.name,
            free: formatBytes(p.free_bytes || 0),
          }),
        })
      );
    acts.push(
      el(
        'label',
        { className: 'tier-days-label' },
        el('span', { textContent: t('tier.slow_label', 'Slower pool') }),
        slow
      )
    );
  }
  acts.push(toggle);
  if (f.enabled && f.watching && !f.learning && !_view.moving) {
    const run = el('button', { type: 'button', className: 'btn-pill-toggle', textContent: t('tier.run', 'Move now') });
    run.dataset.tierAct = 'run';
    run.dataset.tierName = f.name;
    acts.push(run);
  }
  const item = el(
    'li',
    { className: 'scr-row' },
    el(
      'div',
      { className: 'scr-words' },
      el('strong', { textContent: f.name }),
      el('span', { className: 'immich-note', textContent: tieringStatus(f, _view) }),
      f.enabled && f.kind === 'merged' && f.slow_pool && f.mounted !== false
        ? el('span', {
            className: 'immich-note',
            textContent: t('tier.slow_to', 'Old files go to {pool}.', { pool: slowName(f) }),
          })
        : null
    ),
    el('div', { className: 'scr-acts' }, ...acts)
  );
  item.dataset.tierRow = f.name;
  return item;
}

function draw() {
  const card = document.getElementById('tiering-card');
  if (!card || !_view) return;
  const all = _view.folders || [];
  const fit = all.filter((f) => !f.why || f.enabled);
  const unfit = all.filter((f) => f.why && !f.enabled);
  const parts = [
    el('h4', {
      className: 'invite-title',
      id: 'tiering-title',
      textContent: t('tier.title', 'Old files move to the slower drives'),
    }),
    el('p', {
      className: 'invite-meta',
      textContent: t(
        'tier.intro',
        'Files that nobody has opened or changed for a long time move from the fast pool to the slower drives, at {time} each night. The folder still shows every file in one place. Kiboto first watches a folder for as many days as you choose, so it knows which files are used; a file that has moved stays where it moved to. Off until you turn it on for a folder.',
        { time: _view.run_at }
      ),
    }),
  ];
  if (editionLine(_view.edition))
    parts.push(el('p', { className: 'immich-note', id: 'tiering-edition', textContent: editionLine(_view.edition) }));
  if (_view.moving)
    parts.push(
      el('p', {
        className: 'immich-note',
        id: 'tiering-moving',
        textContent: t('tier.moving', 'Files are being moved now.'),
      })
    );
  if (fit.length) {
    const list = el('ul', { className: 'scr-list' });
    list.append(...fit.map(row));
    parts.push(list);
  } else if (unfit.length && unfit.every((f) => f.why === 'no_merged_folder')) {
    parts.push(el('p', { className: 'immich-note', id: 'tiering-none', textContent: tieringWhy('no_merged_folder') }));
  } else {
    parts.push(
      el('p', {
        className: 'immich-note',
        id: 'tiering-none',
        textContent: t('tier.none_fit', 'No shared folder fits yet.'),
      })
    );
  }
  if (unfit.length && !unfit.every((f) => f.why === 'no_merged_folder')) {
    const list = el('ul', { className: 'tier-unfit' });
    for (const f of unfit)
      list.append(el('li', { className: 'immich-note', textContent: `${f.name}: ${tieringWhy(f.why)}` }));
    parts.push(
      el(
        'details',
        { className: 'tier-unfit-box' },
        el('summary', {
          textContent: t(
            'tier.unfit_summary',
            '{count, plural, one {# folder does not fit} other {# folders do not fit}}',
            {
              count: unfit.length,
            }
          ),
        }),
        list
      )
    );
  }
  card.replaceChildren(...parts);
}

function daysOf(name) {
  const card = document.getElementById('tiering-card');
  const input = [...(card?.querySelectorAll('input[data-tier-days]') || [])].find(
    (i) => /** @type {HTMLInputElement} */ (i).dataset.tierDays === name
  );
  return Number(/** @type {HTMLInputElement} */ (input)?.value) || (_view && _view.default_days) || 90;
}

const path = (name) => `/api/tiering/folders/${encodeURIComponent(name)}`;

async function onClick(e) {
  const target = /** @type {HTMLElement} */ (e.target);
  const action = target.dataset?.tierAct;
  const name = target.dataset?.tierName;
  if (!action || !name || !_view) return;
  const folder = (_view.folders || []).find((f) => f.name === name);
  try {
    if (action === 'toggle') {
      const turnOn = !(folder && folder.enabled);
      const days = daysOf(name);
      const payload = { enabled: turnOn, days };
      const slow = /** @type {HTMLSelectElement | null} */ (
        [...document.querySelectorAll('#tiering-card select[data-tier-slow]')].find(
          (s) => /** @type {HTMLElement} */ (s).dataset.tierSlow === name
        )
      );
      if (turnOn && slow) payload.slow = slow.value;
      _view = await api.put(path(name), payload); // the server asks to confirm turning it on
      showToast(
        turnOn
          ? t(
              'tier.turned_on',
              'On for {name}. Kiboto watches the folder for {days, plural, one {# day} other {# days}} before it moves anything.',
              { name, days }
            )
          : t('tier.turned_off', 'Off for {name}. Files that have moved stay where they are.', { name }),
        'success'
      );
    } else if (action === 'run') {
      _view = await api.post(`${path(name)}/run`, {});
      showToast(
        t('tier.started', 'Moving the old files of {name}. The result shows here when it ends.', { name }),
        'success'
      );
    }
  } catch (err) {
    failed(err);
  }
  draw();
}

async function onChange(e) {
  const input = /** @type {HTMLInputElement} */ (e.target);
  const name = input.dataset?.tierDays;
  const folder = name && _view ? (_view.folders || []).find((f) => f.name === name) : null;
  if (!folder || !folder.enabled) return; // for a folder that is off the number is read when it is turned on
  try {
    _view = await api.put(path(name), { enabled: true, days: Number(input.value) || 0 });
    showToast(t('tier.days_saved', 'Saved.'), 'success');
  } catch (err) {
    failed(err);
  }
  draw();
}

/** Draws the card on the Shared folders page; false when it is not shown. */
export async function renderTieringCard() {
  const before = document.getElementById('shares-advanced');
  if (!before || !before.parentNode) return false;
  let card = document.getElementById('tiering-card');
  if (!card) {
    card = el('section', { id: 'tiering-card', className: 'invite-card' });
    card.setAttribute('aria-labelledby', 'tiering-title');
    before.parentNode.insertBefore(card, before);
  }
  try {
    _view = await api.get('/api/tiering');
  } catch {
    card.hidden = true; // not someone who manages the storage, or an older server
    return false;
  }
  card.hidden = false;
  if (!card.dataset.bound) {
    card.dataset.bound = '1';
    card.addEventListener('click', onClick);
    card.addEventListener('change', onChange);
  }
  draw();
  return true;
}

/** For tests: forget what was drawn. */
export function resetTieringCardForTesting() {
  _view = null;
}
