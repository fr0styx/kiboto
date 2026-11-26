/**
 * "Protect this NAS" (FEAT-01): a copy of the shares outside this box in one step. Pick where it
 * goes (a USB disk, another NAS or the cloud), keep or narrow the shares, and it becomes an
 * off-site backup (restic: versions, encrypted) that runs every night at 2:00; the first run
 * starts right away and the recovery kit is offered.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { html } from '../html.js';
import { showToast } from '../toast.js';
import { offerRecoveryKit } from './offsite-backup.js';

const KINDS = [
  {
    kind: 'usb',
    label: () => t('protect.usb', 'A USB disk'),
    help: () => t('protect.usb_help', 'Plugged into this NAS. Keep it somewhere else between backups if you can.'),
    none: () => t('protect.none_usb', 'No USB disk is mounted. Plug one in and mount it, then open this again.'),
  },
  {
    kind: 'nas',
    label: () => t('protect.nas', 'Another NAS'),
    help: () => t('protect.nas_help', 'A share of another NAS mounted here, best in another building.'),
    none: () => t('protect.none_nas', 'No other NAS is mounted here. Mount one of its shares, then open this again.'),
  },
  {
    kind: 'kiboto',
    label: () => t('protect.kiboto', 'Another Kiboto'),
    help: () =>
      t(
        'protect.kiboto_help',
        "A Kiboto paired with this one, best in another home. The copy is encrypted: the other Kiboto can't read it."
      ),
    none: () =>
      t(
        'protect.none_kiboto',
        'No other Kiboto is paired with this one. Pair one under Network → Backup buddy, then open this again.'
      ),
  },
  {
    kind: 'cloud',
    label: () => t('protect.cloud', 'The cloud'),
    help: () => t('protect.cloud_help', 'A cloud storage account set up in Remote storage.'),
    none: () => t('protect.none_cloud', 'No cloud storage is set up. Add it in Remote storage, then open this again.'),
  },
];

/** Shares left unticked at first: Docker's image and VM disks (system), installers (isos). They
 * are large, change all the time or can be downloaded again; anyone can still tick them. */
export const UNTICKED_SHARES = new Set(['system', 'isos']);

/** Where the backup goes inside the chosen destination. */
export function locationFor(kind, target) {
  return kind === 'cloud' ? `rclone:${target}:kiboto-backup` : `${String(target).replace(/\/+$/, '')}/kiboto-backup`;
}

/** A place to pick: a path or remote name, or {value, label} (a paired Kiboto: its id and name). */
const option = (o) => (typeof o === 'string' ? { value: o, label: o } : o);

export function guideHtml(dest, shares) {
  const where = KINDS.map((k) => {
    const options = ((dest && dest[k.kind]) || []).map(option);
    return html`<fieldset class="protect-kind"><legend>${k.label()}</legend><p class="snap-help">${k.help()}</p>${
      options.length
        ? options.map(
            (o) =>
              html`<label class="offsite-check"><input type="radio" name="target" value="${k.kind}|${o.value}"> ${o.label}</label>`
          )
        : html`<p class="offsite-meta">${k.none()}</p>`
    }</fieldset>`;
  });
  const more = html`<details class="protect-more"><summary>${t('protect.more', 'More options')}</summary>
    <label class="offsite-field">${t('protect.hour', 'Every night at (hour, 0–23)')}<input name="hour" type="number" min="0" max="23" value="2"></label>
    <div class="protect-keep"><span>${t('protect.keep', 'Versions kept')}</span>
      <label>${t('offsite.daily', 'Daily versions')}<input name="daily" type="number" min="0" max="1000" value="7"></label>
      <label>${t('offsite.weekly', 'Weekly')}<input name="weekly" type="number" min="0" max="1000" value="4"></label>
      <label>${t('offsite.monthly', 'Monthly')}<input name="monthly" type="number" min="0" max="1000" value="12"></label></div>
    <label class="offsite-field">${t('protect.custom', 'Somewhere else (a folder under /mnt, or rclone:account:folder)')}<input name="custom" maxlength="300" placeholder="/mnt/disks/usb/kiboto"></label>
    <p class="offsite-meta">${t('protect.custom_help', 'Used when no place above is picked. A backup server with a user name and password is set up under Offsite backup below.')}</p>
  </details>`;
  const what = shares.map(
    (s) =>
      html`<label class="offsite-check"><input type="checkbox" name="paths" value="${s.path}" ${UNTICKED_SHARES.has(String(s.name).toLowerCase()) ? '' : html`checked`}> ${s.name}</label>`
  );
  return html`<form class="offsite-form" data-protect-form>
    <p class="snap-help">${t('protect.intro', 'A copy of your shares outside this Kiboto, with versions and encryption, every night at 2:00.')}</p>
    ${where}
    <fieldset><legend>${t('protect.what', 'What')}</legend>${what}</fieldset>
    ${more}
    <button type="submit" class="btn-pill-toggle is-primary">${t('protect.create', 'Protect')}</button>
  </form>`;
}

/** The More options: the hour and the versions kept (empty fields keep the defaults). */
export function scheduleOf(f) {
  const n = (k, d) => (f.get(k) === null || f.get(k) === '' ? d : Math.max(0, Math.round(Number(f.get(k)))));
  return {
    hour: Math.min(23, n('hour', 2)),
    keep: { daily: n('daily', 7), weekly: n('weekly', 4), monthly: n('monthly', 12) },
  };
}

/** Turns the form into an off-site backup; returns its id. A paired Kiboto gives the space first. */
export async function protect(form, names = {}) {
  const f = new FormData(form);
  const custom = String(f.get('custom') || '').trim();
  const target = String(f.get('target') || '') || (custom ? `custom|${custom}` : '');
  const paths = f.getAll('paths').map(String);
  if (!target) throw new Error(t('protect.pick', 'Pick where the copy goes.'));
  if (!paths.length) throw new Error(t('protect.pick_shares', 'Pick at least one share.'));
  const [kind, place] = [target.slice(0, target.indexOf('|')), target.slice(target.indexOf('|') + 1)];
  const { hour, keep } = scheduleOf(f);
  let id;
  if (kind === 'kiboto') {
    // the paired box gives space and the backup is made there (the buddy flow); then the schedule
    await api.post(`/api/fleet/peers/${encodeURIComponent(place)}/backup`, { paths });
    id = `buddy-${place.slice(0, 8)}`;
    const repo = ((await api.get('/api/offsite'))?.repos || []).find((r) => r.id === id);
    if (repo) await api.put('/api/offsite/repos', { id, name: repo.name, location: repo.location, paths, keep, hour });
  } else {
    id = `protect-${kind}-${Date.now().toString(36)}`;
    const label =
      kind === 'custom' ? t('protect.custom_name', 'Backup') : (KINDS.find((k) => k.kind === kind) || KINDS[0]).label();
    await api.put('/api/offsite/repos', {
      id,
      name: `${label}: ${names[place] || place}`,
      location: kind === 'custom' ? place : locationFor(kind, place),
      paths,
      keep,
      hour,
    });
    await api.post(`/api/offsite/repos/${encodeURIComponent(id)}/init`, {});
  }
  await api.post(`/api/offsite/repos/${encodeURIComponent(id)}/backup`, {});
  return id;
}

/** The window: centered on a dimmed backdrop, with the title bar every pop-up gets from
 * dialog-chrome.js (drag, minimize to the dock, maximize, close). */
function guideWindow() {
  let host = document.getElementById('protect-nas');
  if (!host) {
    host = document.createElement('div');
    host.id = 'protect-nas';
    host.className = 'smart-modal-backdrop';
    host.style.zIndex = '10020'; // above Mission Control
    host.innerHTML = html`<div class="smart-modal-window" role="dialog" aria-modal="true" aria-labelledby="protect-nas-title" data-dock-icon="#i-shield" data-minimizable>
      <div class="smart-modal-header">
        <span class="smart-modal-title" id="protect-nas-title"><svg class="ic" aria-hidden="true"><use href="#i-shield"/></svg> ${t('protect.title', 'Protect this Kiboto')}</span>
        <div class="os-window-controls">
          <button type="button" class="win-btn close-btn" data-close title="${t('diagnostics.close_btn', 'Close')}" data-i18n-title="diagnostics.close_btn" aria-label="${t('diagnostics.close_btn', 'Close')}" data-i18n-aria-label="diagnostics.close_btn"></button>
        </div>
      </div>
      <div class="smart-modal-body"></div>
    </div>`;
    document.body.appendChild(host);
    host.querySelector('[data-close]').addEventListener('click', () => closeGuide(host));
    host.addEventListener('click', (e) => {
      if (e.target === host) closeGuide(host);
    });
    host.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeGuide(host);
    });
  }
  return host;
}

export function closeGuide(host = document.getElementById('protect-nas')) {
  if (!host) return;
  host.classList.remove('open');
  host.style.display = 'none';
}

export async function openProtectGuide(preselect = '') {
  const host = guideWindow();
  let names = {};
  const body = host.querySelector('.smart-modal-body');
  body.textContent = t('ui.loading', 'Loading…');
  host.style.display = '';
  host.classList.add('open');
  host.querySelector('[data-close]').focus();
  try {
    const [dest, sh, fleet] = await Promise.all([
      api.get('/api/offsite/destinations'),
      api.get('/api/storage/shares').catch(() => ({ shares: [] })),
      Promise.resolve()
        .then(() => api.get('/api/fleet'))
        .catch(() => null), // only who may set the system up reads it
    ]);
    const shares = (sh.shares || []).filter((s) => s.mountpoint).map((s) => ({ name: s.name, path: s.mountpoint }));
    const peers = (fleet?.peers || []).map((p) => ({
      value: p.id,
      label: p.name || t('protect.kiboto', 'Another Kiboto'),
    }));
    names = Object.fromEntries(peers.map((p) => [p.value, p.label]));
    body.innerHTML = guideHtml({ ...dest, kiboto: peers }, shares);
    // a disk just plugged in comes chosen (Backup 5); a value that is not offered chooses nothing
    const chosen = preselect
      ? /** @type {HTMLInputElement | undefined} */ (
          [...body.querySelectorAll('input[name="target"]')].find(
            (r) => /** @type {HTMLInputElement} */ (r).value === preselect
          )
        )
      : undefined;
    if (chosen) chosen.checked = true;
  } catch (err) {
    body.textContent = err.message || String(err);
    return host;
  }
  body.querySelector('[data-protect-form]').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const id = await protect(e.target, names);
      closeGuide(host);
      showToast(
        t(
          'protect.done',
          'Protection is set up and the first backup has started; it shows in Jobs. Save the recovery kit now.'
        ),
        'success'
      );
      await offerRecoveryKit({ id });
    } catch (err) {
      showToast(err.message || String(err), 'error');
    }
  });
  return host;
}
