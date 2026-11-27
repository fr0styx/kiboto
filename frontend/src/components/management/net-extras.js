/**
 * IPv6 and further routes in the address dialog, on a machine Kiboto runs (managed.py writes them
 * into the port's own networkd file, tried first like any address change). Elsewhere the host's own
 * settings own them and the section stays hidden.
 */
import { t } from '../../i18n.js';

const $ = (id) => document.getElementById(id);

/** A row for one further route: the network, the router it is reached through, and Remove. */
function routeRow(route = { destination: '', gateway: '' }) {
  const row = document.createElement('div');
  row.className = 'net-route-row';
  const dest = document.createElement('input');
  dest.type = 'text';
  dest.className = 'tz-text-input net-route-dest';
  dest.placeholder = t('net.route_dest_ph', 'Network, e.g. 10.20.0.0/16');
  dest.setAttribute('aria-label', t('net.route_dest', 'Network'));
  dest.value = route.destination || '';
  const gw = document.createElement('input');
  gw.type = 'text';
  gw.className = 'tz-text-input net-route-gw';
  gw.placeholder = t('net.route_gw_ph', 'Through router, e.g. 192.168.1.254');
  gw.setAttribute('aria-label', t('net.route_gw', 'Through router'));
  gw.value = route.gateway || '';
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'btn-pill-toggle is-small';
  remove.textContent = t('net.route_remove', 'Remove');
  remove.addEventListener('click', () => row.remove());
  row.append(dest, gw, remove);
  return row;
}

/** Shows the fixed-address fields only when a fixed IPv6 address is chosen. */
function followMode() {
  const fixed = $('net-host-ipv6-static');
  const mode = /** @type {HTMLSelectElement|null} */ ($('net-host-ipv6-mode'));
  if (fixed && mode) fixed.hidden = mode.value !== 'static';
}

/** Fills the section from what the server read (`data`), or hides it where the host owns these. */
export function fillHostExtras(data, managed) {
  const box = $('net-host-extras');
  if (!box) return false;
  box.hidden = !managed;
  if (!managed) return false;
  const mode = /** @type {HTMLSelectElement|null} */ ($('net-host-ipv6-mode'));
  if (mode) {
    mode.value = ['auto', 'off', 'static'].includes(data?.ipv6_mode) ? data.ipv6_mode : 'auto';
    mode.onchange = followMode;
  }
  const addr = /** @type {HTMLInputElement|null} */ ($('net-host-ipv6-address'));
  const gw = /** @type {HTMLInputElement|null} */ ($('net-host-ipv6-gateway'));
  if (addr) addr.value = data?.ipv6_address || '';
  if (gw) gw.value = data?.ipv6_gateway || '';
  followMode();
  const list = $('net-host-routes');
  if (list) {
    list.replaceChildren(...(Array.isArray(data?.routes) ? data.routes : []).map((r) => routeRow(r)));
  }
  const add = $('net-host-route-add');
  if (add) add.onclick = () => list?.append(routeRow());
  return true;
}

/** What the section asks for, for the apply request; {} where it is hidden. */
export function hostExtras() {
  const box = $('net-host-extras');
  if (!box || box.hidden) return {};
  const mode = /** @type {HTMLSelectElement|null} */ ($('net-host-ipv6-mode'))?.value || 'auto';
  const out = { ipv6_mode: mode, routes: [] };
  if (mode === 'static') {
    out.ipv6_address = /** @type {HTMLInputElement|null} */ ($('net-host-ipv6-address'))?.value.trim() || '';
    out.ipv6_gateway = /** @type {HTMLInputElement|null} */ ($('net-host-ipv6-gateway'))?.value.trim() || '';
  }
  for (const row of document.querySelectorAll('#net-host-routes .net-route-row')) {
    const destination = /** @type {HTMLInputElement} */ (row.querySelector('.net-route-dest')).value.trim();
    const gateway = /** @type {HTMLInputElement} */ (row.querySelector('.net-route-gw')).value.trim();
    if (destination || gateway) out.routes.push({ destination, gateway });
  }
  return out;
}
