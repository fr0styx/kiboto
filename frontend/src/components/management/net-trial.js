/**
 * New address settings for this machine are a trial. The machine itself goes back to the settings
 * from before when nobody keeps the new ones in time, so a wrong address locks nobody out. This is
 * the dialog of that trial: a countdown, "Keep the new settings", "Go back now", and, when Kiboto
 * moves to another address, the link that keeps the settings by being opened there.
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { showToast } from '../../toast.js';
import { html } from '../../html.js';
import { showNetDialog, hideNetDialog } from './net-dialog.js';

const ID = 'net-trial-overlay';
let _tick = null;

/** The link that keeps the trial from the new address, when Kiboto moves away from this one. */
export function linkElsewhere(url, here = window.location.hostname) {
  if (!/^https?:\/\//.test(url || '') || !url.includes('keep-network=')) return '';
  try {
    return new URL(url).hostname === here ? '' : url;
  } catch {
    return '';
  }
}

/** The sentence of the dialog while `left` seconds remain, and after. */
export function trialLine(left, away) {
  if (left <= 0) return t('net.trial_back', 'This machine is back on the settings from before.');
  return away
    ? t(
        'net.trial_open_there',
        'Kiboto is moving to a new address. Open it there to keep the new settings. If nobody does within {seconds} seconds, this machine goes back to the settings from before.',
        { seconds: left }
      )
    : t(
        'net.trial_keep_here',
        'If this page still works, keep the new settings. Otherwise this machine goes back to the settings from before in {seconds} seconds.',
        { seconds: left }
      );
}

export function closeNetTrial() {
  if (_tick) clearInterval(_tick);
  _tick = null;
  const overlay = document.getElementById(ID);
  if (!overlay) return;
  hideNetDialog(overlay);
  overlay.remove();
}

/**
 * Shows the trial. `trial` is what applying answered ({canary_id, timeout_sec, url}) or what the
 * host says about a trial already running ({seconds_left}). `after` runs when it is over.
 */
export function showNetTrial(trial, after = () => {}) {
  if (document.getElementById(ID)) return null; // one trial, one dialog
  const seconds = Number(trial?.timeout_sec ?? trial?.seconds_left) || 0;
  const ends = Date.now() + seconds * 1000;
  const link = linkElsewhere(trial?.url);
  const key = trial?.canary_id || null;
  const overlay = document.createElement('div');
  overlay.id = ID;
  overlay.className = 'smart-modal-backdrop';
  overlay.setAttribute('role', 'alertdialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-labelledby', 'net-trial-title');
  overlay.setAttribute('aria-describedby', 'net-trial-text');
  overlay.innerHTML = html`
    <div class="smart-modal-window net-trial-window">
      <div class="smart-modal-header hcfg-x">
        <span class="smart-modal-title hcfg-row" id="net-trial-title">${t('net.trial_title', 'Trying the new network settings')}</span>
      </div>
      <div class="smart-modal-body hcfg-col">
        <p class="net-trial-text" id="net-trial-text"></p>
        ${link ? html`<a class="net-trial-link" id="net-trial-link" href="${link}" target="_blank" rel="noopener">${new URL(link).origin}</a>` : ''}
        <div class="hcfg-row-box">
          <button type="button" class="btn-pill-toggle" id="net-trial-back">${t('net.trial_go_back', 'Go back now')}</button>
          <button type="button" class="btn-pill-toggle active is-primary" id="net-trial-keep">${t('net.trial_keep', 'Keep the new settings')}</button>
        </div>
      </div>
    </div>`;
  document.body.append(overlay);
  const $ = (id) => /** @type {HTMLButtonElement} */ (overlay.querySelector(`#${id}`));
  const text = $('net-trial-text');
  const done = () => {
    closeNetTrial();
    after();
  };
  const draw = () => {
    const left = Math.ceil((ends - Date.now()) / 1000);
    text.textContent = trialLine(left, Boolean(link));
    if (left > 0) return;
    clearInterval(_tick); // over: the machine has gone back; only closing is left
    _tick = null;
    $('net-trial-keep').hidden = true;
    const close = $('net-trial-back');
    close.textContent = t('diagnostics.close_btn', 'Close');
    close.onclick = done;
  };
  const send = async (path, said) => {
    try {
      await api.post(path, { canary_id: key });
    } catch {
      showToast(
        t('net.trial_failed', 'That did not reach this machine. If it has moved to a new address, open Kiboto there.'),
        'error'
      );
      return;
    }
    showToast(said, 'success');
    done();
  };
  $('net-trial-keep').onclick = () =>
    send('/api/network/host/confirm', t('net.trial_kept', 'The new network settings are kept.'));
  $('net-trial-back').onclick = () =>
    send('/api/network/host/revert', t('net.trial_back', 'This machine is back on the settings from before.'));
  draw();
  if (seconds > 0) _tick = setInterval(draw, 1000);
  showNetDialog(overlay, () => {}); // Escape does not decide a trial: a button does, or the clock
  return overlay;
}
