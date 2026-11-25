/* Kiboto service worker (M1): makes the app installable, shows an offline notice,
 * and receives files from the phone's share sheet into the user's Inbox folder.
 * It never caches API responses or files. */
// The page shown when Kiboto doesn't answer, in the browser's language (COMP-02): it tries again
// every few seconds and when the device comes back online, and opens Kiboto as soon as it answers.
const OFFLINE_TEXT = {
  en: [
    'Kiboto is not reachable',
    'Check that this device is on your home network, or connected through Tailscale. Kiboto opens again by itself as soon as it answers.',
    'Try again',
  ],
  de: [
    'Kiboto ist nicht erreichbar',
    'Prüfen Sie, ob dieses Gerät im Heimnetz oder über Tailscale verbunden ist. Kiboto öffnet sich von selbst wieder, sobald es antwortet.',
    'Erneut versuchen',
  ],
  fr: [
    'Kiboto est injoignable',
    "Vérifiez que cet appareil est sur votre réseau domestique ou connecté via Tailscale. Kiboto se rouvre tout seul dès qu'il répond.",
    'Réessayer',
  ],
  es: [
    'No se puede conectar con Kiboto',
    'Comprueba que este dispositivo está en tu red de casa o conectado por Tailscale. Kiboto se abrirá solo en cuanto responda.',
    'Reintentar',
  ],
  zh: ['无法连接 Kiboto', '请确认此设备在你的家庭网络中，或已通过 Tailscale 连接。Kiboto 一有响应就会自动重新打开。', '重试'],
};
const MARK =
  '<svg aria-hidden="true" viewBox="6 6 52 52" width="56" height="56"><path fill-rule="evenodd" fill="currentColor" d="M19 6H45A13 13 0 0 1 58 19V37.5A2.5 2.5 0 0 1 55.5 40H8.5A2.5 2.5 0 0 1 6 37.5V19A13 13 0 0 1 19 6ZM8.5 42.5H55.5A2.5 2.5 0 0 1 58 45V45A13 13 0 0 1 45 58H19A13 13 0 0 1 6 45V45A2.5 2.5 0 0 1 8.5 42.5ZM19 13H45A6.5 6.5 0 0 1 51.5 19.5V27A6.5 6.5 0 0 1 45 33.5H19A6.5 6.5 0 0 1 12.5 27V19.5A6.5 6.5 0 0 1 19 13ZM46.05 50.25A3.2 3.2 0 1 0 52.45 50.25A3.2 3.2 0 1 0 46.05 50.25ZM24.75 17.75A3.25 3.25 0 0 1 28 21V25.5A3.25 3.25 0 0 1 21.5 25.5V21A3.25 3.25 0 0 1 24.75 17.75ZM39.25 17.75A3.25 3.25 0 0 1 42.5 21V25.5A3.25 3.25 0 0 1 36 25.5V21A3.25 3.25 0 0 1 39.25 17.75Z"/></svg>';

/** The offline page for an Accept-Language header (or a language tag): English when none is known. */
function offlinePage(languages) {
  const wanted = String(languages || '')
    .split(',')
    .map((part) => part.trim().slice(0, 2).toLowerCase());
  const lang = wanted.find((code) => OFFLINE_TEXT[code]) || 'en';
  const [title, body, retry] = OFFLINE_TEXT[lang];
  return (
    `<!doctype html><html lang="${lang}"><head><meta charset="utf-8">` +
    '<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="dark light">' +
    `<title>${title}</title><style>` +
    ':root{--bg:#0a0a0a;--ink:#e8eef0;--muted:#9fb0b4;--brand:#2fbfae;--on-brand:#04201d}' +
    '@media (prefers-color-scheme: light){:root{--bg:#f2f6fa;--ink:#13201f;--muted:#4b5d60;--brand:#0a7a70;--on-brand:#fff}}' +
    'body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);' +
    'font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}' +
    'main{max-width:30rem;padding:24px;text-align:center}svg{color:var(--brand)}' +
    'h1{font-size:1.4rem;margin:16px 0 8px}p{color:var(--muted);margin:0 0 24px}' +
    'button{font:inherit;font-weight:600;padding:10px 22px;min-height:44px;border-radius:10px;border:0;' +
    'background:var(--brand);color:var(--on-brand);cursor:pointer}button:focus-visible{outline:3px solid var(--ink);outline-offset:3px}' +
    `</style></head><body><main>${MARK}<h1>${title}</h1><p>${body}</p>` +
    `<button id="retry" type="button">${retry}</button></main><script>` +
    "const again=()=>fetch('/',{method:'HEAD',cache:'no-store'}).then((r)=>{if(r.ok)location.reload();}).catch(()=>{});" +
    "document.getElementById('retry').addEventListener('click',again);addEventListener('online',again);setInterval(again,5000);" +
    '</script></body></html>'
  );
}

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (req.method === 'POST' && url.pathname === '/share-target') {
    event.respondWith(receiveShare(req));
    return;
  }
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(
        () =>
          new Response(offlinePage(req.headers.get('accept-language') || self.navigator?.language), {
            headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
          })
      )
    );
  }
});

async function upload(name, body, type) {
  return fetch(`/api/fs/inbox?filename=${encodeURIComponent(name)}`, {
    method: 'POST',
    body,
    credentials: 'same-origin',
    headers: { 'Content-Type': type || 'application/octet-stream' },
  });
}

async function receiveShare(request) {
  let form;
  try {
    form = await request.formData();
  } catch (e) {
    return Response.redirect('/?shared=error', 303);
  }
  const files = form.getAll('files').filter((f) => f && typeof f === 'object' && f.name);
  const text = ['title', 'text', 'url'].map((k) => form.get(k)).filter(Boolean).join('\n');
  let saved = 0;
  let failed = 0;
  const items = files.map((f) => [f.name, f, f.type]);
  if (!items.length && text) {
    const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-');
    items.push([`Shared note ${stamp}.txt`, new Blob([text], { type: 'text/plain' }), 'text/plain']);
  }
  for (const [name, body, type] of items) {
    const res = await upload(name, body, type).catch(() => null);
    if (res && res.status === 401) return Response.redirect('/?shared=login', 303);
    if (res && res.ok) saved += 1;
    else failed += 1;
  }
  return Response.redirect(`/?shared=${saved}&failed=${failed}`, 303);
}

// Alerts from the NAS (M1): the server encrypts them for this browser
self.addEventListener('push', (event) => {
  let msg;
  try {
    msg = event.data ? event.data.json() : {};
  } catch (e) {
    msg = { title: 'Kiboto', body: event.data ? event.data.text() : '' };
  }
  event.waitUntil(
    self.registration.showNotification(msg.title || 'Kiboto', {
      body: msg.body || '',
      icon: '/img/icon-192.png',
      badge: '/img/icon-192.png',
      tag: msg.tag || undefined,
      requireInteraction: msg.level === 'critical',
      data: { url: msg.url || '/' },
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
      const open = wins.find((w) => new URL(w.url).origin === self.location.origin);
      if (open) return open.focus();
      return self.clients.openWindow(url);
    })
  );
});
