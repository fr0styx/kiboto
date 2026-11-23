// This machine: the clock and the SSH switch of a machine set up for Kiboto; hidden where Kiboto is a guest.
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
    post: async (url, body) => {
      puts.push([url, body]);
      if (putFails) throw putFails;
      return { status: 'trial', canary_id: 'k', timeout_sec: 60, url: '' };
    },
    put: async (url, body) => {
      puts.push([url, body]);
      if (putFails) throw putFails;
      if ('ssh' in body) state = { ...state, ssh: { ...state.ssh, on: body.ssh } };
      if ('clock_automatic' in body) state = { ...state, clock: { ...state.clock, automatic: body.clock_automatic } };
      return state;
    },
  },
}));

const { renderMachineCard, clockStatus, sshStatus, bridgeStatus, systemDiskStatus } =
  await import('../components/management/machine-card.js');
const trial = vi.hoisted(() => ({ showNetTrial: vi.fn() }));
vi.mock('../components/management/net-trial.js', () => trial);

const flush = () => new Promise((r) => setTimeout(r, 0));
const mount = () => /** @type {HTMLElement} */ (document.getElementById('machine-card'));
const el = (id) => /** @type {HTMLButtonElement} */ (mount().querySelector(`#${id}`));

beforeEach(() => {
  puts.length = 0;
  putFails = null;
  state = {
    managed: true,
    host_name: 'attic',
    time_zone: 'Europe/Berlin',
    clock: { can: true, automatic: true, in_step: true },
    ssh: { installed: true, on: true },
    bridge: { on: false, port: '', can: true },
  };
  document.body.innerHTML = '<div id="machine-card" hidden></div>';
});

describe('This machine', () => {
  it('says how the clock stands', () => {
    expect(clockStatus(null)).toBe('This machine has nothing that sets its clock.');
    expect(clockStatus({ can: false })).toBe('This machine has nothing that sets its clock.');
    expect(clockStatus({ can: true, automatic: false })).toBe('Off: the clock is not checked and can drift.');
    expect(clockStatus({ can: true, automatic: true, in_step: false })).toBe('On: waiting for the first answer.');
    expect(clockStatus({ can: true, automatic: true, in_step: true })).toBe('On: the clock is in step.');
  });

  it('says how full the system disk is and what lives elsewhere', async () => {
    expect(systemDiskStatus(null)).toBe('');
    expect(systemDiskStatus({ total_bytes: 0 })).toBe('');
    expect(systemDiskStatus({ total_bytes: 32 * 1024 ** 3, free_bytes: 20 * 1024 ** 3 })).toContain(
      'shared folders and apps live on the pools'
    );
    state = { ...state, system_disk: { total_bytes: 32 * 1024 ** 3, free_bytes: 20 * 1024 ** 3 } };
    await renderMachineCard();
    expect(mount().querySelector('#machine-system-disk')?.textContent).toContain('20');
  });

  it('says how SSH stands', () => {
    expect(sshStatus(null)).toBe('SSH is not installed on this machine.');
    expect(sshStatus({ installed: false })).toBe('SSH is not installed on this machine.');
    expect(sshStatus({ installed: true, on: true })).toContain('can sign in to its command line');
    expect(sshStatus({ installed: true, on: false })).toBe(
      'Off: the command line can be used only at the machine itself.'
    );
  });

  it('stays hidden where Kiboto is a guest, and when it cannot be read', async () => {
    state = { managed: false };
    expect(await renderMachineCard()).toEqual({ managed: false });
    expect(mount().hidden).toBe(true);
    expect(mount().innerHTML).toBe('');
    state = new Error('403');
    expect(await renderMachineCard()).toBe(null);
    expect(mount().hidden).toBe(true);
    document.body.innerHTML = '';
    expect(await renderMachineCard()).toBe(null);
  });

  it('shows the name, the zone and both switches', async () => {
    await renderMachineCard();
    expect(mount().hidden).toBe(false);
    expect(mount().querySelector('#machine-called')?.textContent).toBe('Called attic. Time zone: Europe/Berlin.');
    expect(el('machine-clock-toggle').getAttribute('aria-pressed')).toBe('true');
    expect(el('machine-clock-toggle').textContent).toBe('On');
    expect(el('machine-ssh-toggle').classList.contains('active')).toBe(true);
    expect(el('machine-ssh-toggle').disabled).toBe(false);
  });

  it('leaves the zone out when the machine has none, and greys what the machine lacks', async () => {
    state = { managed: true, host_name: 'attic', time_zone: '', clock: { can: false }, ssh: { installed: false } };
    await renderMachineCard();
    expect(mount().querySelector('#machine-called')?.textContent).toBe('Called attic.');
    expect(el('machine-clock-toggle').disabled).toBe(true);
    expect(el('machine-ssh-toggle').disabled).toBe(true);
    expect(el('machine-ssh-toggle').textContent).toBe('Off');
    state = { managed: true, host_name: 'attic', time_zone: '' };
    await renderMachineCard();
    expect(el('machine-ssh-toggle').disabled).toBe(true);
  });

  it('turns SSH off and the clock off, and draws what the machine then says', async () => {
    await renderMachineCard();
    el('machine-ssh-toggle').click();
    await flush();
    expect(puts).toEqual([['/api/system/machine', { ssh: false }]]);
    expect(el('machine-ssh-toggle').getAttribute('aria-pressed')).toBe('false');
    el('machine-clock-toggle').click();
    await flush();
    expect(puts[1]).toEqual(['/api/system/machine', { clock_automatic: false }]);
    expect(mount().querySelector('#machine-clock-status')?.textContent).toBe(
      'Off: the clock is not checked and can drift.'
    );
  });

  it('says why a change was not taken, and stays quiet when the person says no', async () => {
    await renderMachineCard();
    putFails = new Error('The machine did not take the change.');
    el('machine-ssh-toggle').click();
    await flush();
    const err = /** @type {HTMLElement} */ (mount().querySelector('#machine-error'));
    expect(err.hidden).toBe(false);
    expect(err.textContent).toBe('The machine did not take the change.');
    await renderMachineCard();
    putFails = { error: 'cancelled' };
    el('machine-ssh-toggle').click();
    await flush();
    expect(/** @type {HTMLElement} */ (mount().querySelector('#machine-error')).hidden).toBe(true);
    putFails = { error: 'other' };
    el('machine-clock-toggle').click();
    await flush();
    expect(mount().querySelector('#machine-error')?.textContent).toBe('The machine did not take the change.');
  });

  it('says how the bridge for virtual machines stands', () => {
    expect(bridgeStatus(null)).toContain('set up outside Kiboto');
    expect(bridgeStatus({ can: false })).toContain('set up outside Kiboto');
    expect(bridgeStatus({ can: true, on: true, port: 'enp1s0' })).toContain('through enp1s0');
    expect(bridgeStatus({ can: true, on: true })).toContain('through -');
    expect(bridgeStatus({ can: true, on: false })).toContain('through this machine only');
  });

  it('turns the bridge on as a trial of the new network settings', async () => {
    await renderMachineCard();
    expect(el('machine-bridge-toggle').getAttribute('aria-pressed')).toBe('false');
    el('machine-bridge-toggle').click();
    await flush();
    await flush();
    expect(puts.at(-1)).toEqual(['/api/network/host/bridge', { on: true }]);
    expect(trial.showNetTrial).toHaveBeenCalledWith(
      { status: 'trial', canary_id: 'k', timeout_sec: 60, url: '' },
      expect.any(Function)
    );
    putFails = new Error("This machine's network is not run by systemd-networkd.");
    el('machine-bridge-toggle').click();
    await flush();
    expect(el('machine-error').textContent).toContain('systemd-networkd');
    putFails = {};
    el('machine-bridge-toggle').click();
    await flush();
    expect(el('machine-error').textContent).toBe('The machine did not take the change.');
  });
});
