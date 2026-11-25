/**
 * The family portal's card in Away from home (ADR 0007): on or off, who may use it, and a
 * single-use join link for each person. The portal itself is /portal on the share links' port.
 */
import { api } from '../../api.js';
import '../../styles/80-public-apps.css'; // the list styles it shares with the other cards there
import { formatDate } from '../../format.js';
import { t } from '../../i18n.js';
import { showToast } from '../../toast.js';
import { html } from '../../html.js';
import { escapeHtml } from '../../utils.js';

const $ = (id) => document.getElementById(id);
const esc = escapeHtml;
const links = new Map(); // user id -> the join link made this visit (it is shown once)

/** What the person is sent with their join link. */
export function portalMessage(name, url) {
  return t(
    'fp.msg',
    'Hi {name}! Open this on your phone to see your files from our Kiboto. It works once, for 7 days: {url}',
    {
      name,
      url,
    }
  );
}

function personState(p) {
  if (!p.allowed) return t('fp.not_allowed', 'Not allowed');
  if (p.signed_in) return t('fp.signed_in', 'Signed in now');
  if (p.passkey) return t('fp.has_passkey', 'Has a passkey');
  if (p.invite_until)
    return t('fp.link_until', 'Join link works until {date}', { date: formatDate(new Date(p.invite_until * 1000)) });
  return t('fp.no_passkey', 'Allowed · no passkey yet');
}

function personHtml(p) {
  const id = esc(String(p.id));
  const link = links.get(String(p.id));
  const buttons = [
    `<button type="button" class="btn-pill-toggle is-small" data-fp-allow="${id}" aria-pressed="${p.allowed}">${esc(
      p.allowed ? t('fp.stop', 'Stop') : t('fp.allow', 'Allow')
    )}</button>`,
  ];
  if (p.allowed && !p.passkey)
    buttons.push(
      `<button type="button" class="btn-pill-toggle is-small is-primary" data-fp-join="${id}">${esc(t('fp.join', 'Join link'))}</button>`
    );
  if (p.invite_until)
    buttons.push(
      `<button type="button" class="btn-pill-toggle is-small is-danger" data-fp-withdraw="${id}">${esc(t('fp.withdraw', 'Withdraw link'))}</button>`
    );
  const copy = link
    ? `<button type="button" class="btn-pill-toggle is-small" data-fp-copy="${id}">${esc(t('fp.copy', 'Copy message'))}</button>`
    : '';
  return `<li class="pa-item"><span><strong>${esc(p.name)}</strong> · ${esc(personState(p))}</span><span>${buttons.join(' ')} ${copy}</span></li>`;
}

function stepsHtml(f) {
  if (!f || f.ready) return '';
  const items = [];
  if (!f.funnel && f.approve_url)
    items.push(
      `<a href="${esc(f.approve_url)}" target="_blank" rel="noopener">${esc(t('fp.step_funnel', 'Allow Funnel for this NAS'))}</a>`
    );
  if (!f.https && f.dns_url)
    items.push(
      `<a href="${esc(f.dns_url)}" target="_blank" rel="noopener">${esc(t('fp.step_https', 'Turn on HTTPS certificates'))}</a>`
    );
  if (!items.length) return '';
  return `<div class="nsv-xs-muted">${esc(t('fp.steps', 'Before it can go online, allow two things in Tailscale (once):'))}</div><ul class="pa-list">${items
    .map((i) => `<li class="pa-item">${i}</li>`)
    .join('')}</ul>`;
}

/** The card's body from GET /api/network/family-portal. */
export function familyPortalHtml(v) {
  if (!v.tailscale)
    return `<div class="nsv-xs-muted">${esc(t('fp.needs_tailscale', 'The family portal goes online through Tailscale. Connect Tailscale first.'))}</div>`;
  let status = t('fp.off', 'Off. Nothing of it is on the internet.');
  if (v.on && v.live) status = t('fp.on_at', 'On at {address}', { address: v.address });
  else if (v.on) status = t('fp.on_not_live', "On, but Tailscale isn't publishing it right now.");
  const toggle = `<button type="button" class="btn-pill-toggle" data-fp="toggle" aria-pressed="${!!v.on}">${esc(
    v.on ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off')
  )}</button>`;
  const people = (v.people || []).map(personHtml).join('');
  return `<div class="nsv-row-4"><span class="nsv-xs-muted" aria-live="polite">${esc(status)}</span>${toggle}</div>
    ${v.on ? '' : stepsHtml(v.funnel)}
    <ul class="pa-list">${people}</ul>
    <div class="nsv-xs-muted-2">${esc(
      t(
        'fp.help',
        "For family members who can't install Tailscale: their own files and photos in a browser, from anywhere, signed in with a passkey. Nothing else of the NAS is reachable there."
      )
    )}</div>`;
}

let last = null;

function render(v) {
  last = v;
  const body = $('fp-body');
  if (body) body.innerHTML = familyPortalHtml(v);
}

async function act(fn) {
  try {
    const v = await fn();
    if (v && v.people) render(v);
    if (v && v.error) showToast(v.error, 'error');
    return v;
  } catch (err) {
    if (/** @type {any} */ (err).status !== 428) showToast(/** @type {Error} */ (err).message, 'error');
    return null;
  }
}

/** Handles a click in the card (exported for the tests). */
export async function onPortalClick(e) {
  const el = /** @type {Element} */ (e.target);
  const hit = (attr) => el.closest(`[${attr}]`)?.getAttribute(attr);
  if (hit('data-fp') === 'toggle' && last) await act(() => api.put('/api/network/family-portal', { on: !last.on }));
  const allow = hit('data-fp-allow');
  if (allow && last) {
    const p = last.people.find((x) => String(x.id) === allow);
    await act(() =>
      api.put(`/api/network/family-portal/people/${encodeURIComponent(allow)}`, { allowed: !p?.allowed })
    );
  }
  const join = hit('data-fp-join');
  if (join) {
    const made = await act(() => api.post(`/api/network/family-portal/people/${encodeURIComponent(join)}/invite`, {}));
    if (made && made.link) {
      links.set(join, made.link);
      await act(() => api.get('/api/network/family-portal'));
    }
  }
  const withdraw = hit('data-fp-withdraw');
  if (withdraw) {
    links.delete(withdraw);
    await act(() => api.delete(`/api/network/family-portal/people/${encodeURIComponent(withdraw)}/invite`));
  }
  const copy = hit('data-fp-copy');
  if (copy && links.has(copy) && last) {
    const p = last.people.find((x) => String(x.id) === copy);
    try {
      await navigator.clipboard.writeText(portalMessage(p?.name || '', links.get(copy)));
      showToast(t('fp.copied', 'Copied: paste it into a message to them.'), 'success');
    } catch {
      showToast(links.get(copy), 'info'); // copying didn't work here: show it to copy by hand
    }
  }
}

function cardShell() {
  let card = $('fp-card');
  if (card) return card;
  const grid = $('away-cards-grid');
  if (!grid) return null;
  card = document.createElement('div');
  card.className = 'nsv-col-box';
  card.id = 'fp-card';
  card.innerHTML = String(html`<div class="nsv-row-4"><span class="nsv-fs18" aria-hidden="true">🏡</span>
    <div class="nsv-fs13-bold-strong">${t('fp.title', 'Family portal')}</div></div>
    <div id="fp-body">…</div>`);
  grid.appendChild(card);
  return card;
}

/** Loads the card and wires it once. */
export async function loadFamilyPortalCard() {
  const card = cardShell();
  if (!card) return;
  if (!card.dataset.bound) {
    card.dataset.bound = '1';
    card.addEventListener('click', onPortalClick);
  }
  try {
    render(await api.get('/api/network/family-portal'));
  } catch (err) {
    const body = $('fp-body');
    if (body) body.textContent = /** @type {Error} */ (err).message || '';
  }
}
