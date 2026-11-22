/**
 * Kernel, ZFS and Docker (Updates), on a machine set up for Kiboto. Those three are held: they
 * move only to the versions a Kiboto release was tested with. The card shows what is installed,
 * whether the tested versions can be brought in, and when a restart finishes a new kernel. Where
 * Kiboto is a guest the card stays hidden: the host updates itself.
 */
import { api } from '../api.js';
import { html } from '../html.js';
import { t } from '../i18n.js';

const GROUPS = [
  { id: 'kernel', pkg: 'linux-image-amd64', name: () => t('hset.kernel', 'Kernel') },
  { id: 'zfs', pkg: 'zfs-dkms', name: () => 'ZFS' },
  { id: 'docker', pkg: 'docker.io', name: () => 'Docker' },
];

/** The sentence under the title. */
export function hostSetStatus(st) {
  if (st.running) return t('hset.running', 'Bringing them up to date… Apps keep running.');
  const last = st.last || {};
  if (last.result === 'failed') return t('hset.failed', 'The last try did not work: {error}', { error: last.error });
  if (last.result === 'zfs_missing') return last.error;
  if (st.restart_needed) return t('hset.restart', 'Restart this machine to finish: the new kernel starts then.');
  if (st.move?.length) return t('hset.can_move', 'Versions this Kiboto was tested with are ready to install.');
  if (st.waiting?.length)
    return t('hset.waiting', 'Debian offers newer versions. They come with a Kiboto update once they are tested.');
  return t('hset.ok', 'As tested with this Kiboto.');
}

function rows(st) {
  const by = Object.fromEntries((st.packages || []).map((p) => [p.name, p]));
  return GROUPS.map(({ id, pkg, name }) => {
    const p = by[pkg] || {};
    const moves = (st.move || []).includes(pkg);
    return html`<li id="hset-${id}">
      <strong>${name()}</strong>
      <span translate="no">${p.installed || '-'}</span>
      ${moves ? html`<span>${t('hset.to', 'to {version}', { version: p.tested })}</span>` : ''}
    </li>`;
  });
}

/** Draws the card into mount and wires it; returns the state shown (null when there is none). */
export async function renderHostSetCard(mount = document.getElementById('host-set-card'), shown = null) {
  if (!mount) return null;
  let st = shown;
  if (!st) {
    try {
      st = await api.get('/api/system/host-set');
    } catch {
      st = null; // an older server, or no right to see it: no card
    }
  }
  if (!st || !st.managed) {
    mount.hidden = true;
    mount.innerHTML = '';
    return st;
  }
  const canMove = Boolean(st.move?.length) && !st.running;
  mount.innerHTML = html`<div class="fw-head">
      <div>
        <h3 class="account-h" id="hset-title">${t('hset.title', 'Kernel, ZFS and Docker')}</h3>
        <p class="fw-status" id="hset-status" aria-live="polite">${hostSetStatus(st)}</p>
      </div>
    </div>
    <p class="fw-why">
      ${t(
        'hset.help',
        'Debian updates everything else on this machine. These three move only to versions a Kiboto release was tested with, so a new kernel never comes up without your pools.'
      )}
    </p>
    <ul class="pcopy-list" aria-labelledby="hset-title">
      ${rows(st)}
    </ul>
    <div class="ddns-actions">
      <button type="button" class="btn-pill-toggle" id="hset-check">${t('hset.check', 'Check Debian')}</button>
      ${
        canMove
          ? html`<button type="button" class="btn-pill-toggle is-primary" id="hset-apply">${t('hset.apply', 'Install the tested versions')}</button>`
          : ''
      }
    </div>
    <div class="fw-error" id="hset-error" role="alert" hidden></div>`;
  mount.hidden = false;
  const $ = (id) => /** @type {any} */ (mount.querySelector(`#${id}`));
  const send = async (path, button) => {
    button.disabled = true;
    try {
      await renderHostSetCard(mount, await api.post(path, {}));
    } catch (e) {
      if (/** @type {any} */ (e)?.error === 'cancelled') {
        button.disabled = false;
        return;
      }
      $('hset-error').textContent = e instanceof Error ? e.message : String(e);
      $('hset-error').hidden = false;
      button.disabled = false;
    }
  };
  $('hset-check').addEventListener('click', () => send('/api/system/host-set/check', $('hset-check')));
  $('hset-apply')?.addEventListener('click', () => send('/api/system/host-set/apply', $('hset-apply')));
  return st;
}
