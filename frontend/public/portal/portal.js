/**
 * The family portal page (ADR 0007): sign in with a passkey (or make one from a join link), then a
 * person's own folders, pictures and files. Talks only to /portal/api; carries its own words in five
 * languages, since none of Kiboto's own scripts load here.
 */

export const TEXT = {
  en: {
    off: 'The family portal is turned off.',
    signin_title: 'Your files and photos',
    signin_help: 'Sign in with the passkey on this device.',
    signin: 'Sign in with passkey',
    join_title: 'Welcome',
    join_help: 'Make a passkey on this device: your fingerprint, face or screen lock will open your files from now on.',
    join: 'Make my passkey',
    no_passkeys: 'This browser can’t use passkeys here. Try another browser, or update this one.',
    signout: 'Sign out',
    up: 'Back',
    empty: 'Nothing here yet.',
    asleep: 'This folder is on a drive that is asleep. Try again later.',
    close: 'Close',
    failed: 'That didn’t work: {why}',
  },
  de: {
    off: 'Das Familienportal ist ausgeschaltet.',
    signin_title: 'Ihre Dateien und Fotos',
    signin_help: 'Melden Sie sich mit dem Passkey auf diesem Gerät an.',
    signin: 'Mit Passkey anmelden',
    join_title: 'Willkommen',
    join_help: 'Legen Sie einen Passkey auf diesem Gerät an: Ab jetzt öffnen Fingerabdruck, Gesicht oder Displaysperre Ihre Dateien.',
    join: 'Passkey anlegen',
    no_passkeys: 'Dieser Browser kann hier keine Passkeys nutzen. Versuchen Sie einen anderen Browser oder aktualisieren Sie diesen.',
    signout: 'Abmelden',
    up: 'Zurück',
    empty: 'Hier ist noch nichts.',
    asleep: 'Dieser Ordner liegt auf einem Laufwerk, das schläft. Versuchen Sie es später noch einmal.',
    close: 'Schließen',
    failed: 'Das hat nicht geklappt: {why}',
  },
  fr: {
    off: 'Le portail familial est désactivé.',
    signin_title: 'Vos fichiers et photos',
    signin_help: 'Connectez-vous avec la clé d’accès de cet appareil.',
    signin: 'Se connecter avec une clé d’accès',
    join_title: 'Bienvenue',
    join_help: 'Créez une clé d’accès sur cet appareil : votre empreinte, votre visage ou le verrouillage de l’écran ouvriront désormais vos fichiers.',
    join: 'Créer ma clé d’accès',
    no_passkeys: 'Ce navigateur ne peut pas utiliser de clés d’accès ici. Essayez un autre navigateur ou mettez celui-ci à jour.',
    signout: 'Se déconnecter',
    up: 'Retour',
    empty: 'Rien ici pour l’instant.',
    asleep: 'Ce dossier est sur un disque en veille. Réessayez plus tard.',
    close: 'Fermer',
    failed: 'Ça n’a pas marché : {why}',
  },
  es: {
    off: 'El portal familiar está desactivado.',
    signin_title: 'Tus archivos y fotos',
    signin_help: 'Inicia sesión con la llave de acceso de este dispositivo.',
    signin: 'Entrar con llave de acceso',
    join_title: 'Te damos la bienvenida',
    join_help: 'Crea una llave de acceso en este dispositivo: tu huella, tu cara o el bloqueo de pantalla abrirán tus archivos desde ahora.',
    join: 'Crear mi llave de acceso',
    no_passkeys: 'Este navegador no puede usar llaves de acceso aquí. Prueba otro navegador o actualiza este.',
    signout: 'Cerrar sesión',
    up: 'Atrás',
    empty: 'Aquí aún no hay nada.',
    asleep: 'Esta carpeta está en un disco que duerme. Vuelve a intentarlo más tarde.',
    close: 'Cerrar',
    failed: 'No ha funcionado: {why}',
  },
  zh: {
    off: '家庭门户已关闭。',
    signin_title: '你的文件和照片',
    signin_help: '用此设备上的通行密钥登录。',
    signin: '用通行密钥登录',
    join_title: '欢迎',
    join_help: '在此设备上创建通行密钥：从现在起，你的指纹、面容或屏幕锁就能打开你的文件。',
    join: '创建我的通行密钥',
    no_passkeys: '此浏览器在这里无法使用通行密钥。请换一个浏览器，或更新此浏览器。',
    signout: '退出',
    up: '返回',
    empty: '这里还没有内容。',
    asleep: '此文件夹所在的硬盘正在休眠。请稍后再试。',
    close: '关闭',
    failed: '没有成功：{why}',
  },
};

/** The first of the browser's languages the portal speaks, else English. */
export function pickLang(languages) {
  for (const tag of languages || []) {
    const code = String(tag).slice(0, 2).toLowerCase();
    if (TEXT[code]) return code;
  }
  return 'en';
}

let lang = 'en';
export function setLang(code) {
  lang = TEXT[code] ? code : 'en';
}
export function tr(key, vars = {}) {
  const s = TEXT[lang][key] || TEXT.en[key] || key;
  return s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ''));
}

/** base64url text → ArrayBuffer */
export function fromB64(text) {
  const s = String(text || '')
    .replace(/-/g, '+')
    .replace(/_/g, '/');
  const bin = atob(s + '==='.slice((s.length + 3) % 4));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

/** ArrayBuffer (or a view) → base64url text */
export function toB64(buf) {
  const bytes =
    buf instanceof ArrayBuffer ? new Uint8Array(buf) : new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 1) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

const withIds = (list) => (list || []).map((c) => ({ ...c, id: fromB64(c.id) }));

export function creationOptions(pk) {
  return {
    ...pk,
    challenge: fromB64(pk.challenge),
    user: { ...pk.user, id: fromB64(pk.user.id) },
    excludeCredentials: withIds(pk.excludeCredentials),
  };
}

export function requestOptions(pk) {
  const out = { ...pk, challenge: fromB64(pk.challenge) };
  if (pk.allowCredentials) out.allowCredentials = withIds(pk.allowCredentials);
  return out;
}

export function credentialJSON(cred) {
  if (typeof cred.toJSON === 'function') return cred.toJSON();
  const r = cred.response;
  const response = { clientDataJSON: toB64(r.clientDataJSON) };
  for (const k of ['attestationObject', 'authenticatorData', 'signature', 'userHandle'])
    if (r[k]) response[k] = toB64(r[k]);
  return { id: cred.id, rawId: toB64(cred.rawId), type: cred.type, response, clientExtensionResults: {} };
}

const PICTURES = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif', '.avif', '.bmp', '.dng']);
const VIDEOS = new Set(['.mp4', '.mov', '.m4v', '.webm', '.mkv']);

/** "folder", "picture", "video" or "file" for a folder entry. */
export function kindOf(entry) {
  if (entry.is_dir) return 'folder';
  const ext = String(entry.ext || (entry.name.match(/\.[^.]+$/) || [''])[0]).toLowerCase();
  if (PICTURES.has(ext)) return 'picture';
  return VIDEOS.has(ext) ? 'video' : 'file';
}

/** The join token from the address's #join=…, or "". */
export function joinToken(hash) {
  const m = /(?:^#|&)join=([A-Za-z0-9_-]{20,})/.exec(hash || '');
  return m ? m[1] : '';
}

const ICON = { folder: '📁', picture: '🖼️', video: '🎬', file: '📄' };
const q = (path) => encodeURIComponent(path);

async function call(method, url, body) {
  const res = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.detail || data.message || String(res.status));
    /** @type {any} */ (err).status = res.status;
    throw err;
  }
  return data;
}

/** One folder's entries as list items (built with DOM calls: names never become markup). */
export function entryNodes(doc, entries) {
  return entries
    .filter((e) => e.name !== '..')
    .map((e) => {
      const kind = kindOf(e);
      const li = doc.createElement('li');
      li.className = 'item';
      const el = doc.createElement(kind === 'file' || kind === 'video' ? 'a' : 'button');
      if (el.tagName === 'A') {
        el.setAttribute('href', `/portal/api/file?path=${q(e.path)}`);
        el.setAttribute('download', e.name);
      } else {
        el.setAttribute('type', 'button');
        el.dataset.kind = kind;
        el.dataset.path = e.path;
      }
      const thumb = doc.createElement('span');
      thumb.className = 'thumb';
      if (kind === 'picture') {
        const img = doc.createElement('img');
        img.loading = 'lazy';
        img.alt = '';
        img.src = `/portal/api/picture?thumb=1&path=${q(e.path)}&v=${Math.round(e.mtime || 0)}`;
        thumb.appendChild(img);
      } else thumb.textContent = ICON[kind];
      const name = doc.createElement('span');
      name.className = 'name';
      name.textContent = e.name;
      el.append(thumb, name);
      li.appendChild(el);
      return li;
    });
}

function screen(nodes) {
  const app = document.getElementById('portal-app');
  app.replaceChildren(...nodes);
}

function el(tag, attrs = {}, text = '') {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text) node.textContent = text;
  return node;
}

function failed(err) {
  return el('p', { class: 'error', role: 'alert' }, tr('failed', { why: err.message }));
}

const trail = [];

async function showFolder(path) {
  let data;
  try {
    data = await call('GET', `/portal/api/list?path=${q(path)}`);
  } catch (err) {
    if (err.status === 401) return showSignIn();
    screen([err.status === 409 ? el('p', { class: 'muted' }, tr('asleep')) : failed(err)]);
    return;
  }
  const bar = el('div', { class: 'path' });
  if (trail.length) {
    const up = el('button', { type: 'button', class: 'plain' }, `← ${tr('up')}`);
    up.addEventListener('click', () => showFolder(trail.pop()));
    bar.appendChild(up);
  }
  const here = String(data.current || '').split('/').filter(Boolean).pop() || '';
  if (here) bar.appendChild(el('strong', {}, here));
  const list = el('ul', { class: 'grid' });
  const nodes = entryNodes(document, data.dirs || []);
  list.append(...nodes);
  list.addEventListener('click', (ev) => {
    const btn = /** @type {HTMLElement} */ (ev.target).closest('button[data-path]');
    if (!btn) return;
    if (btn.dataset.kind === 'folder') {
      trail.push(path);
      showFolder(btn.dataset.path);
    } else openPicture(btn.dataset.path);
  });
  screen([bar, nodes.length ? list : el('p', { class: 'muted' }, tr('empty'))]);
}

function openPicture(path) {
  const view = /** @type {HTMLDialogElement} */ (document.getElementById('portal-view'));
  /** @type {HTMLImageElement} */ (document.getElementById('portal-img')).src = `/portal/api/picture?path=${q(path)}`;
  view.showModal();
}

function signedIn(name) {
  document.getElementById('portal-who').textContent = name || '';
  const out = document.getElementById('portal-signout');
  out.hidden = false;
  trail.length = 0;
  showFolder('');
}

function passkeysHere() {
  return typeof window.PublicKeyCredential === 'function' && !!navigator.credentials;
}

function showSignIn() {
  document.getElementById('portal-signout').hidden = true;
  document.getElementById('portal-who').textContent = '';
  const btn = el('button', { type: 'button' }, tr('signin'));
  const status = el('p', { class: 'muted' });
  btn.addEventListener('click', async () => {
    status.replaceChildren();
    try {
      const opts = await call('POST', '/portal/api/signin/options');
      const cred = await navigator.credentials.get({ publicKey: requestOptions(opts.options.publicKey) });
      const done = await call('POST', '/portal/api/signin/finish', { ticket: opts.ticket, credential: credentialJSON(cred) });
      signedIn(done.name);
    } catch (err) {
      status.replaceChildren(failed(err));
    }
  });
  const box = el('div', { class: 'center' });
  box.append(el('h2', {}, tr('signin_title')), el('p', { class: 'muted' }, tr('signin_help')));
  box.append(passkeysHere() ? btn : el('p', { class: 'error' }, tr('no_passkeys')), status);
  screen([box]);
}

function showJoin(token) {
  const btn = el('button', { type: 'button' }, tr('join'));
  const status = el('p', { class: 'muted' });
  btn.addEventListener('click', async () => {
    status.replaceChildren();
    try {
      const opts = await call('POST', '/portal/api/join/options', { token });
      const cred = await navigator.credentials.create({ publicKey: creationOptions(opts.options.publicKey) });
      const done = await call('POST', '/portal/api/join/finish', {
        token,
        ticket: opts.ticket,
        credential: credentialJSON(cred),
      });
      history.replaceState(null, '', location.pathname); // the token leaves the address bar
      signedIn(done.name);
    } catch (err) {
      status.replaceChildren(failed(err));
    }
  });
  const box = el('div', { class: 'center' });
  box.append(el('h2', {}, tr('join_title')), el('p', { class: 'muted' }, tr('join_help')));
  box.append(passkeysHere() ? btn : el('p', { class: 'error' }, tr('no_passkeys')), status);
  screen([box]);
}

export async function start() {
  setLang(pickLang(navigator.languages || [navigator.language]));
  document.documentElement.lang = lang;
  const out = document.getElementById('portal-signout');
  out.textContent = tr('signout');
  out.addEventListener('click', async () => {
    await call('POST', '/portal/api/signout').catch(() => {});
    showSignIn();
  });
  const close = document.getElementById('portal-close');
  close.textContent = tr('close');
  close.addEventListener('click', () => /** @type {HTMLDialogElement} */ (document.getElementById('portal-view')).close());
  let state;
  try {
    state = await call('GET', '/portal/api/state');
  } catch (err) {
    screen([failed(err)]);
    return;
  }
  if (!state.on) return screen([el('p', { class: 'center muted' }, tr('off'))]);
  if (state.signed_in) return signedIn(state.name);
  const token = joinToken(location.hash);
  return token ? showJoin(token) : showSignIn();
}

if (typeof document !== 'undefined' && document.getElementById('portal-app')) start();
