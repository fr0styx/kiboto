/**
 * "Bring your files over" (re-audit R5): copy folders from another NAS or a PC on the network
 * into a shared folder here. Connect (a Windows share or SSH), choose the folder there and the
 * shared folder here, see what would be copied, copy, and have it checked: a second pass that
 * copies nothing means every file is here with the same size and date.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { formatBytes } from '../format.js';

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const c of children) node.append(c);
  return node;
}

/** The name the connection is saved under: letters, digits and dashes from the address. */
export function remoteName(host) {
  const slug = String(host || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40);
  return `movein-${slug || 'source'}`;
}

/** rclone's fields for the two ways in. */
export function parametersFor(kind, { host, user, pass }) {
  const base = { host: String(host || '').trim(), user: String(user || '').trim(), pass: String(pass || '') };
  return kind === 'sftp' ? { ...base, port: 22 } : base;
}

/** Where a folder lands: inside the chosen shared folder, under its own name. */
export function targetPath(sharePath, folder) {
  const name = String(folder || '')
    .split('/')
    .filter(Boolean)
    .pop();
  const base = String(sharePath || '').replace(/\/+$/, '');
  return name ? `${base}/${name}` : base;
}

/** Tests the connection, then saves it. Throws with the other machine's answer when it fails. */
export async function connect(kind, fields) {
  const parameters = parametersFor(kind, fields);
  const tested = await api.post('/api/remotes/test', { type: kind, parameters });
  if (!tested || !tested.success) throw new Error((tested && tested.error) || t('movein.no_answer', 'no answer'));
  const name = remoteName(parameters.host);
  await api.post('/api/remotes', { name, type: kind, parameters });
  return name;
}

/** The folders at the top of the other machine (for a Windows share: its shares). */
export async function listFolders(name) {
  const items = (await api.get(`/api/remotes/${encodeURIComponent(name)}/files`)) || [];
  return items
    .filter((i) => i.IsDir)
    .map((i) => i.Path || i.Name)
    .sort((a, b) => a.localeCompare(b));
}

/**
 * Polls a copy job until it has finished; onProgress gets each reading.
 * @param {string} id
 * @param {(job: any) => void} [onProgress]
 * @param {(ms: number) => Promise<unknown>} [sleep]
 */
export async function waitForJob(id, onProgress = () => {}, sleep = (ms) => new Promise((r) => setTimeout(r, ms))) {
  for (;;) {
    const job = await api.get(`/api/remotes/sync/jobs/${encodeURIComponent(id)}`);
    onProgress(job);
    if (job.status !== 'running') return job;
    await sleep(1500);
  }
}

async function run(name, folder, target, dryRun, onProgress, sleep) {
  const started = await api.post('/api/remotes/sync', {
    src: `${name}:${folder}`,
    dst: target,
    action: 'copy',
    dry_run: dryRun,
    notify: !dryRun,
  });
  const job = await waitForJob(started.id, onProgress, sleep);
  if (job.status !== 'success') throw new Error(job.error || t('movein.copy_stopped', 'the copy stopped'));
  return job;
}

/** What a copy would move: {files, bytes}. Nothing is written. Also the check after a copy. */
export async function preview(name, folder, target, sleep) {
  const job = await run(name, folder, target, true, () => {}, sleep);
  return { files: job.total_files || 0, bytes: job.total_bytes || 0 };
}

export function copy(name, folder, target, onProgress, sleep) {
  return run(name, folder, target, false, onProgress, sleep);
}

function field(labelText, input) {
  return el('label', { className: 'movein-field' }, el('span', { textContent: labelText }), input);
}

function buildForm() {
  const kind = (value, text, checked) =>
    el(
      'label',
      { className: 'movein-kind' },
      el('input', { type: 'radio', name: 'movein-kind', value, checked }),
      el('span', { textContent: text })
    );
  const host = el('input', { type: 'text', name: 'host', className: 'tz-text-input', required: true });
  host.autocomplete = 'off';
  host.placeholder = '192.168.1.20';
  const user = el('input', { type: 'text', name: 'user', className: 'tz-text-input' });
  user.autocomplete = 'off';
  const pass = el('input', { type: 'password', name: 'pass', className: 'tz-text-input' });
  pass.autocomplete = 'off';
  return el(
    'form',
    { className: 'movein-step' },
    el('p', {
      className: 'kb-muted',
      textContent: t(
        'movein.intro',
        'Copies folders from another NAS or a PC on your network into a shared folder here. Nothing is changed or deleted on the other machine.'
      ),
    }),
    el(
      'fieldset',
      { className: 'movein-kinds' },
      el('legend', { textContent: t('movein.where', 'Where are the files now?') }),
      kind('smb', t('movein.kind_smb', 'Another NAS or a PC (a Windows share)'), true),
      kind('sftp', t('movein.kind_sftp', 'A machine you reach with SSH'), false)
    ),
    field(t('movein.host', 'Its address or name on the network'), host),
    field(t('movein.user', 'Account name there'), user),
    field(t('movein.pass', 'Password there'), pass),
    el('button', {
      type: 'submit',
      className: 'btn-pill-toggle is-primary',
      textContent: t('movein.connect', 'Connect'),
    })
  );
}

function select(name, values, labels = values) {
  const s = el('select', { name, className: 'tz-select-input' });
  values.forEach((v, i) => s.append(el('option', { value: v, textContent: labels[i] })));
  return s;
}

/** The window's steps, kept in one place so tests can drive them without the frame. */
export function startMoveIn(body, deps = {}) {
  const d = { connect, listFolders, preview, copy, shares: loadShares, forget: forgetConnection, ...deps };
  const status = el('p', { className: 'movein-status' });
  status.setAttribute('role', 'status');
  const say = (text) => {
    status.textContent = text;
  };
  const fail = (key, english, e) => say(t(key, english, { error: e?.message || String(e || '') }));
  const form = buildForm();
  const choose = el('div', { className: 'movein-step', hidden: true });
  const done = el('div', { className: 'movein-step', hidden: true });
  body.replaceChildren(form, choose, done, status);
  let name = '';

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = new FormData(form);
    say(t('movein.connecting', 'Connecting…'));
    try {
      name = await d.connect(String(data.get('movein-kind')), {
        host: data.get('host'),
        user: data.get('user'),
        pass: data.get('pass'),
      });
      const [folders, shares] = await Promise.all([d.listFolders(name), d.shares()]);
      if (!folders.length) return say(t('movein.no_folders', 'Connected, but that account sees no folders there.'));
      if (!shares.length) return say(t('movein.no_shares', 'Make a shared folder here first: the files need a place.'));
      showChoose(folders, shares);
    } catch (err) {
      fail('movein.connect_failed', "Couldn't connect: {error}", err);
    }
    return undefined;
  });

  function showChoose(folders, shares) {
    form.hidden = true;
    const from = select('from', folders);
    const into = select(
      'into',
      shares.map((s) => s.path),
      shares.map((s) => s.name)
    );
    const look = el('button', {
      type: 'button',
      className: 'btn-pill-toggle',
      textContent: t('movein.preview', 'See what would be copied'),
    });
    const go = el('button', {
      type: 'button',
      className: 'btn-pill-toggle is-primary',
      textContent: t('movein.copy', 'Copy now'),
      hidden: true,
    });
    choose.replaceChildren(
      field(t('movein.from', 'Folder on the other machine'), from),
      field(t('movein.into', 'Into this shared folder'), into),
      look,
      go
    );
    choose.hidden = false;
    say('');
    const target = () => targetPath(into.value, from.value);
    const reset = () => {
      go.hidden = true;
    };
    from.addEventListener('change', reset);
    into.addEventListener('change', reset);
    look.addEventListener('click', async () => {
      say(t('movein.looking', 'Looking at both sides…'));
      try {
        const p = await d.preview(name, from.value, target());
        if (!p.files) return say(t('movein.nothing', 'Everything in that folder is already here.'));
        say(
          t('movein.would', '{count, plural, one {# file} other {# files}} ({size}) would be copied into {target}.', {
            count: p.files,
            size: formatBytes(p.bytes),
            target: target(),
          })
        );
        go.hidden = false;
      } catch (err) {
        fail('movein.look_failed', "Couldn't compare the two sides: {error}", err);
      }
      return undefined;
    });
    go.addEventListener('click', async () => {
      look.disabled = go.disabled = from.disabled = into.disabled = true;
      try {
        await d.copy(name, from.value, target(), (job) =>
          say(
            t('movein.progress', 'Copying… {percent}% ({done} of {total})', {
              percent: Math.round(job.percent || 0),
              done: formatBytes(job.bytes_transferred || 0),
              total: formatBytes(job.total_bytes || 0),
            })
          )
        );
        say(t('movein.checking', 'Copied. Checking that every file arrived…'));
        const left = await d.preview(name, from.value, target());
        showDone(target(), left.files);
      } catch (err) {
        fail(
          'movein.copy_failed',
          "The copy didn't finish: {error}. Files already copied stay; copy again to go on.",
          err
        );
        look.disabled = go.disabled = from.disabled = into.disabled = false;
      }
    });
  }

  function showDone(target, missing) {
    choose.hidden = true;
    say(
      missing
        ? t(
            'movein.missing',
            '{count, plural, one {# file is} other {# files are}} still missing in {target}. Copy again to fetch the rest.',
            { count: missing, target }
          )
        : t('movein.done', 'Copied and checked: every file is in {target}.', { target })
    );
    const again = el('button', {
      type: 'button',
      className: 'btn-pill-toggle',
      textContent: missing ? t('movein.again', 'Copy again') : t('movein.another', 'Copy another folder'),
    });
    const forget = el('button', {
      type: 'button',
      className: 'btn-pill-toggle',
      textContent: t('movein.forget', 'Forget the connection to the other machine'),
    });
    done.replaceChildren(again, forget);
    done.hidden = false;
    again.addEventListener('click', () => {
      done.hidden = true;
      choose.hidden = false;
      choose.querySelectorAll('button, select').forEach((c) => {
        /** @type {HTMLButtonElement} */ (c).disabled = false;
      });
    });
    forget.addEventListener('click', async () => {
      try {
        await d.forget(name);
        forget.disabled = true;
        again.hidden = true;
        say(t('movein.forgotten', 'The connection and its password are removed from this NAS. The copied files stay.'));
      } catch (err) {
        fail('movein.forget_failed', "Couldn't remove the connection: {error}", err);
      }
    });
  }

  return { form, choose, done, status };
}

async function loadShares() {
  const res = await api.get('/api/storage/shares');
  return ((res && res.shares) || []).filter((s) => s.mountpoint).map((s) => ({ name: s.name, path: s.mountpoint }));
}

function forgetConnection(name) {
  return api.delete(`/api/remotes/${encodeURIComponent(name)}`);
}

function closeMoveIn(host) {
  host.classList.remove('open');
  host.style.display = 'none';
}

/** The window: the frame every pop-up gets, with the steps inside. */
export function openMoveIn() {
  let host = document.getElementById('move-in');
  if (!host) {
    host = el('div', { id: 'move-in', className: 'smart-modal-backdrop' });
    host.style.zIndex = '10020';
    const title = el('span', {
      className: 'smart-modal-title',
      id: 'move-in-title',
      textContent: t('movein.title', 'Bring your files over'),
    });
    const close = el('button', { type: 'button', className: 'win-btn close-btn' });
    close.title = t('diagnostics.close_btn', 'Close');
    close.setAttribute('aria-label', t('diagnostics.close_btn', 'Close'));
    const win = el(
      'div',
      { className: 'smart-modal-window' },
      el('div', { className: 'smart-modal-header' }, title, el('div', { className: 'os-window-controls' }, close)),
      el('div', { className: 'smart-modal-body movein-body' })
    );
    win.setAttribute('role', 'dialog');
    win.setAttribute('aria-modal', 'true');
    win.setAttribute('aria-labelledby', 'move-in-title');
    host.append(win);
    document.body.append(host);
    close.addEventListener('click', () => closeMoveIn(host));
    host.addEventListener('click', (e) => {
      if (e.target === host) closeMoveIn(host);
    });
    host.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeMoveIn(host);
    });
  }
  startMoveIn(/** @type {HTMLElement} */ (host.querySelector('.movein-body')));
  host.style.display = '';
  host.classList.add('open');
  /** @type {HTMLElement} */ (host.querySelector('input[name="host"]')).focus();
  return host;
}
