// SNMP v3 on Connections (owner decision, 16 Nov 2026): off by default; the passwords never come back.
import { describe, it, expect, vi, beforeEach } from 'vitest';

let state;
const puts = [];
let putFails = null;
vi.mock('../api.js', () => ({
  api: {
    get: async () => {
      if (state instanceof Error) throw state;
      return state;
    },
    put: async (url, body) => {
      puts.push([url, body]);
      if (putFails) throw putFails;
      state = { ...state, ...body, passwords_set: state.passwords_set || Boolean(body.auth_password) };
      return state;
    },
  },
}));

const { renderSnmpCard, snmpStatus } = await import('../components/management/snmp-card.js');

beforeEach(() => {
  puts.length = 0;
  putFails = null;
  state = {
    enabled: false,
    port: 161,
    user: '',
    passwords_set: false,
    running: false,
    error: '',
    protocols: { auth: 'SHA-256', priv: 'AES-128' },
  };
  document.body.innerHTML = '<div id="conn-snmp-card"></div>';
});

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('SNMP card', () => {
  it('says what state the agent is in', () => {
    expect(snmpStatus(null)).toBe('Off');
    expect(snmpStatus({ enabled: true, running: true, port: 161, listening_port: 161, user: 'monitor' })).toBe(
      'Answers SNMP v3 on UDP 161 as monitor.'
    );
    expect(snmpStatus({ enabled: true, error: 'UDP 161 could not be opened: in use' })).toBe(
      'Not answering: UDP 161 could not be opened: in use'
    );
    expect(snmpStatus({ enabled: true, running: false })).toBe('On, starting…');
  });

  it('is off by default, names the protocols and sends the passwords only when typed', async () => {
    const mount = /** @type {HTMLElement} */ (document.getElementById('conn-snmp-card'));
    await renderSnmpCard();
    expect(mount.querySelector('#snmp-status')?.textContent).toBe('Off');
    expect(mount.textContent).toContain('Authentication password (SHA-256)');
    expect(mount.textContent).toContain('Encryption password (AES-128)');
    /** @type {HTMLInputElement} */ (mount.querySelector('#snmp-user')).value = 'monitor';
    /** @type {HTMLInputElement} */ (mount.querySelector('#snmp-auth')).value = 'auth-pass-1';
    /** @type {HTMLInputElement} */ (mount.querySelector('#snmp-priv')).value = 'priv-pass-2';
    /** @type {HTMLElement} */ (mount.querySelector('#snmp-toggle')).click();
    await flush();
    await flush();
    expect(puts[0]).toEqual([
      '/api/network/snmp',
      {
        enabled: true,
        port: 161,
        user: 'monitor',
        auth_password: 'auth-pass-1',
        priv_password: 'priv-pass-2',
        location: '',
        contact: '',
      },
    ]);
    // drawn again: the passwords are not in the page, only said to be saved
    const auth = /** @type {HTMLInputElement} */ (mount.querySelector('#snmp-auth'));
    expect(auth.value).toBe('');
    expect(auth.placeholder).toBe('Saved; type a new one to change it');
    mount.querySelector('form')?.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(puts[1][1].auth_password).toBeNull();
    expect(puts[1][1].enabled).toBe(true);
  });

  it('shows why a save failed and stays quiet when the confirmation is cancelled', async () => {
    const mount = /** @type {HTMLElement} */ (document.getElementById('conn-snmp-card'));
    await renderSnmpCard();
    putFails = new Error('Fill in the user name and both passwords before turning it on.');
    /** @type {HTMLElement} */ (mount.querySelector('#snmp-toggle')).click();
    await flush();
    const err = /** @type {HTMLElement} */ (mount.querySelector('#snmp-error'));
    expect(err.hidden).toBe(false);
    expect(err.textContent).toBe('Fill in the user name and both passwords before turning it on.');
    err.hidden = true;
    putFails = Object.assign(new Error('Cancelled'), { error: 'cancelled' });
    /** @type {HTMLElement} */ (mount.querySelector('#snmp-toggle')).click();
    await flush();
    expect(err.hidden).toBe(true);
  });

  it('says when it cannot be loaded, and does nothing without its place', async () => {
    state = new Error('forbidden');
    await renderSnmpCard();
    expect(document.body.textContent).toContain('SNMP could not be loaded: forbidden');
    expect(await renderSnmpCard(null)).toBeNull();
  });
});
