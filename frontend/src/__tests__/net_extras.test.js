// IPv6 and further routes in the address dialog: shown only on a machine Kiboto runs, and sent
// with the address change.
import { describe, it, expect, beforeEach } from 'vitest';

const { fillHostExtras, hostExtras } = await import('../components/management/net-extras.js');

const DIALOG = `
  <div id="net-host-extras" hidden>
    <select id="net-host-ipv6-mode">
      <option value="auto">auto</option><option value="off">off</option><option value="static">static</option>
    </select>
    <div id="net-host-ipv6-static" hidden>
      <input id="net-host-ipv6-address"><input id="net-host-ipv6-gateway">
    </div>
    <div id="net-host-routes"></div>
    <button id="net-host-route-add" type="button"></button>
  </div>`;

const $ = (id) => document.getElementById(id);

describe('IPv6 and routes in the address dialog', () => {
  beforeEach(() => {
    document.body.innerHTML = DIALOG;
  });

  it('stays hidden, and sends nothing, where the host owns these settings', () => {
    expect(fillHostExtras({ ipv6_mode: 'static' }, false)).toBe(false);
    expect($('net-host-extras').hidden).toBe(true);
    expect(hostExtras()).toEqual({});
  });

  it('is a no-op without the section in the page', () => {
    document.body.innerHTML = '';
    expect(fillHostExtras({}, true)).toBe(false);
    expect(hostExtras()).toEqual({});
  });

  it('fills what the machine has, and sends it back as asked', () => {
    fillHostExtras(
      {
        ipv6_mode: 'static',
        ipv6_address: '2001:db8::50/64',
        ipv6_gateway: 'fe80::1',
        routes: [{ destination: '10.20.0.0/16', gateway: '192.168.1.254' }],
      },
      true
    );
    expect($('net-host-extras').hidden).toBe(false);
    expect($('net-host-ipv6-static').hidden).toBe(false);
    expect(document.querySelectorAll('.net-route-row')).toHaveLength(1);
    expect(hostExtras()).toEqual({
      ipv6_mode: 'static',
      ipv6_address: '2001:db8::50/64',
      ipv6_gateway: 'fe80::1',
      routes: [{ destination: '10.20.0.0/16', gateway: '192.168.1.254' }],
    });
  });

  it('adds and removes route rows, and skips empty ones', () => {
    fillHostExtras({ ipv6_mode: 'nonsense', routes: 'not a list' }, true);
    expect(/** @type {HTMLSelectElement} */ ($('net-host-ipv6-mode')).value).toBe('auto');
    expect($('net-host-ipv6-static').hidden).toBe(true);
    $('net-host-route-add').click();
    $('net-host-route-add').click();
    const rows = document.querySelectorAll('.net-route-row');
    expect(rows).toHaveLength(2);
    /** @type {HTMLInputElement} */ (rows[0].querySelector('.net-route-dest')).value = ' 2001:db8:5::/48 ';
    /** @type {HTMLInputElement} */ (rows[0].querySelector('.net-route-gw')).value = 'fe80::2';
    expect(hostExtras()).toEqual({
      ipv6_mode: 'auto',
      routes: [{ destination: '2001:db8:5::/48', gateway: 'fe80::2' }],
    });
    /** @type {HTMLButtonElement} */ (rows[0].querySelector('button')).click();
    expect(document.querySelectorAll('.net-route-row')).toHaveLength(1);
    expect(hostExtras()).toEqual({ ipv6_mode: 'auto', routes: [] });
  });

  it('shows the fixed-address fields when a fixed address is chosen', () => {
    fillHostExtras({ ipv6_mode: 'off' }, true);
    const mode = /** @type {HTMLSelectElement} */ ($('net-host-ipv6-mode'));
    mode.value = 'static';
    mode.dispatchEvent(new Event('change'));
    expect($('net-host-ipv6-static').hidden).toBe(false);
    expect(hostExtras()).toEqual({ ipv6_mode: 'static', ipv6_address: '', ipv6_gateway: '', routes: [] });
  });
});
