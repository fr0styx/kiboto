/**
 * This machine: on a machine set up for Kiboto, what it is called, its time zone, whether its
 * clock is set from the internet, and the switch for signing in to its command line over the
 * network (SSH). Where Kiboto is a guest (Unraid, a Docker host) the card stays hidden: all of
 * that belongs to the host.
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';

/** The line under "Set the clock from the internet". */
export function clockStatus(clock) {
  if (!clock || !clock.can) return t('machine.clock_cannot', 'This machine has nothing that sets its clock.');
  if (!clock.automatic) return t('machine.clock_off', 'Off: the clock is not checked and can drift.');
  return clock.in_step
    ? t('machine.clock_in_step', 'On: the clock is in step.')
    : t('machine.clock_waiting', 'On: waiting for the first answer.');
}

/** The line under "Virtual machines on the home network". */
export function bridgeStatus(bridge) {
  if (!bridge || !bridge.can)
    return t('machine.bridge_cannot', "This machine's network is set up outside Kiboto, so Kiboto leaves it alone.");
  return bridge.on
    ? t('machine.bridge_on', 'On: virtual machines get an address on your home network, through {port}.', {
        port: bridge.port || '-',
      })
    : t('machine.bridge_off', 'Off: virtual machines reach the network through this machine only.');
}

/** The line under "Command line over the network (SSH)". */
export function sshStatus(ssh) {
  if (!ssh || !ssh.installed) return t('machine.ssh_missing', 'SSH is not installed on this machine.');
  return ssh.on
    ? t('machine.ssh_on', 'On: someone with an account on this machine can sign in to its command line.')
    : t('machine.ssh_off', 'Off: the command line can be used only at the machine itself.');
}

function row(id, icon, title, status, on, usable) {
  const label = on ? t('nas_name.btn_on', 'On') : t('nas_name.btn_off', 'Off');
  return `
    <div class="nsv-row-3">
      <div class="nsv-row-4">
        <span class="nsv-fs18" aria-hidden="true">${icon}</span>
        <div>
          <div class="nsv-fs13-bold-strong" id="${id}-title">${escapeHtml(title)}</div>
          <div class="nsv-xs-muted" id="${id}-status">${escapeHtml(status)}</div>
        </div>
      </div>
      <button type="button" class="btn-pill-toggle${on ? ' active' : ''}" id="${id}-toggle" aria-pressed="${on ? 'true' : 'false'}" aria-labelledby="${id}-title ${id}-toggle"${usable ? '' : ' disabled'}>${escapeHtml(label)}</button>
    </div>`;
}

function html(st) {
  const called = st.time_zone
    ? t('machine.called', 'Called {name}. Time zone: {zone}.', { name: st.host_name, zone: st.time_zone })
    : t('machine.called_only', 'Called {name}.', { name: st.host_name });
  const clock = st.clock || {};
  const ssh = st.ssh || {};
  return `
    <div class="nsv-row-4">
      <span class="nsv-fs18" aria-hidden="true">🖥️</span>
      <div>
        <div class="nsv-fs13-bold-strong" id="machine-title">${escapeHtml(t('machine.title', 'This machine'))}</div>
        <div class="nsv-xs-muted" id="machine-called">${escapeHtml(called)}</div>
      </div>
    </div>
    <div class="nsv-xs-muted-2">${escapeHtml(t('machine.help', 'The name is the one in the card above. The time zone is the one chosen for Kiboto.'))}</div>
    ${row('machine-clock', '🕒', t('machine.clock', 'Set the clock from the internet'), clockStatus(clock), Boolean(clock.automatic), Boolean(clock.can))}
    ${row('machine-ssh', '⌨️', t('machine.ssh', 'Command line over the network (SSH)'), sshStatus(ssh), Boolean(ssh.on), Boolean(ssh.installed))}
    ${row('machine-bridge', '🖧', t('machine.bridge', 'Virtual machines on the home network'), bridgeStatus(st.bridge), Boolean(st.bridge?.on), Boolean(st.bridge?.can))}
    <div class="ddns-error" id="machine-error" role="alert" hidden></div>`;
}

/** Draws the card into mount and wires it; returns the state shown (null when it could not be read). */
export async function renderMachineCard(mount = document.getElementById('machine-card')) {
  if (!mount) return null;
  let st = null;
  try {
    st = await api.get('/api/system/machine');
  } catch {
    st = null; // an older server, or no right to see it: no card
  }
  if (!st || !st.managed) {
    mount.hidden = true;
    mount.innerHTML = '';
    return st;
  }
  mount.hidden = false;
  mount.innerHTML = html(st);
  const $ = (id) => /** @type {any} */ (mount.querySelector(`#${id}`));
  const send = async (body) => {
    try {
      await api.put('/api/system/machine', body);
    } catch (e) {
      if (/** @type {any} */ (e)?.error === 'cancelled') return;
      const err = $('machine-error');
      err.textContent =
        e instanceof Error && e.message ? e.message : t('machine.failed', 'The machine did not take the change.');
      err.hidden = false;
      return;
    }
    await renderMachineCard(mount);
  };
  $('machine-clock-toggle').addEventListener('click', () => send({ clock_automatic: !st.clock.automatic }));
  $('machine-ssh-toggle').addEventListener('click', () => send({ ssh: !st.ssh.on }));
  // a bridge changes where the machine's address lives: a trial, kept or undone like an address change
  $('machine-bridge-toggle').addEventListener('click', async () => {
    try {
      const trial = await api.post('/api/network/host/bridge', { on: !st.bridge?.on });
      const m = await import('./net-trial.js');
      m.showNetTrial(trial, () => renderMachineCard(mount));
    } catch (e) {
      const err = $('machine-error');
      err.textContent =
        e instanceof Error && e.message ? e.message : t('machine.failed', 'The machine did not take the change.');
      err.hidden = false;
    }
  });
  return st;
}
