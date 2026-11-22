/**
 * Settings copy on your pools (Backup), on a machine set up for Kiboto: per pool, when the
 * encrypted copy of Kiboto's settings on it was last written, and a button to write it now. A
 * sleeping pool is never woken for it.
 *
 * Below it, the way back after the machine was set up again: "Look on the drives" finds the
 * settings an earlier Kiboto left on them, and its recovery key brings them back. Looking reads
 * every drive, so it happens only when asked. Where Kiboto is a guest the card stays hidden.
 */
import { api } from '../api.js';
import { formatDateTime } from '../format.js';
import { html } from '../html.js';
import { t } from '../i18n.js';

const when = (seconds) => formatDateTime(new Date(seconds * 1000));

/** What a pool's line says; `done` is what "Copy now" just answered for it. */
export function poolCopyLine(pool, done = '') {
  if (done === 'asleep') return t('pcopy.asleep', 'Asleep: it keeps the copy it has');
  if (pool.error) return t('pcopy.failed', 'Last try failed: {error}', { error: pool.error });
  if (!pool.at) return t('pcopy.never', 'No copy yet');
  return t('pcopy.at', 'Copied {when}', { when: when(pool.at) });
}

function earlier(st, looked) {
  const found = st.found || [];
  return html`<h3 class="account-h" id="pcopy-earlier-title">${t('pcopy.earlier_title', 'Settings from an earlier Kiboto')}</h3>
    <p class="fw-why">
      ${t(
        'pcopy.earlier_help',
        'If this machine was set up again, its drives may still hold the settings of the Kiboto before. Looking reads every drive, so sleeping drives wake up.'
      )}
    </p>
    ${
      found.length
        ? html`<ul class="pcopy-list" id="pcopy-found" aria-labelledby="pcopy-earlier-title">
          ${found.map(
            (c) =>
              html`<li>
                <span
                  >${t('pcopy.found_line', '{name}, copied {when}, on pool {pool}', {
                    name: c.name,
                    when: when(c.at),
                    pool: c.pool,
                  })}</span
                >
                <button type="button" class="btn-pill-toggle is-small pcopy-bring" data-key="${c.key}">
                  ${t('pcopy.bring_back', 'Bring back')}
                </button>
              </li>`
          )}
        </ul>`
        : ''
    }
    ${
      looked && !found.length
        ? html`<p class="fw-why" id="pcopy-nothing">
          ${t('pcopy.nothing', 'No settings of an earlier Kiboto were found on the drives.')}
        </p>`
        : ''
    }
    <div class="ddns-actions">
      <button type="button" class="btn-pill-toggle" id="pcopy-look">${t('pcopy.look', 'Look on the drives')}</button>
    </div>
    <form class="ddns-form" id="pcopy-restore" hidden>
      <p class="fw-why" id="pcopy-restore-note"></p>
      <label class="ddns-field"
        ><span id="pcopy-restore-label"></span>
        <input id="pcopy-restore-key" type="text" autocomplete="off" spellcheck="false" maxlength="64" placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"
      /></label>
      <div class="ddns-actions">
        <button type="button" class="btn-pill-toggle" id="pcopy-restore-cancel">${t('net.cancel', 'Cancel')}</button>
        <button type="submit" class="btn-pill-toggle is-primary" id="pcopy-restore-go">
          ${t('pcopy.restore_go', 'Bring the settings back')}
        </button>
      </div>
    </form>
    <p class="fw-status" id="pcopy-restore-done" role="status" hidden></p>`;
}

/** Draws the card into mount and wires it; returns the state shown (null when there is none). */
export async function renderPoolCopyCard(
  mount = document.getElementById('pool-copy-card'),
  shown = null,
  looked = false
) {
  if (!mount) return null;
  let st = shown;
  if (!st) {
    try {
      st = await api.get('/api/system/settings-copy');
    } catch {
      st = null; // an older server, or no right to see it: no card
    }
  }
  if (!st || !st.managed) {
    mount.hidden = true;
    mount.innerHTML = '';
    return st;
  }
  const pools = st.pools || [];
  const done = st.done || {};
  const locked = t(
    'pcopy.locked',
    "No copy can be written until the recovery key has opened this machine's data key (Security)."
  );
  const none = t('pcopy.none', 'No pools yet. The copy starts with your first pool.');
  const whyNot = st.locked ? locked : pools.length ? '' : none;
  mount.innerHTML = html`<h2 class="account-h" id="pcopy-title">${t('pcopy.title', 'Settings copy on your pools')}</h2>
    <p class="fw-why">
      ${t(
        'pcopy.help',
        'Kiboto keeps an encrypted copy of its settings on every pool. If the system disk fails, a fresh Kiboto and your recovery key bring your people, shared folders and apps back. A sleeping pool is not woken for it.'
      )}
    </p>
    ${st.locked ? html`<p class="fw-why" id="pcopy-locked">${locked}</p>` : ''}
    ${
      pools.length
        ? html`<ul class="pcopy-list" aria-labelledby="pcopy-title">
          ${pools.map(
            (p) =>
              html`<li><strong translate="no">${p.name}</strong> <span>${poolCopyLine(p, done[p.name])}</span></li>`
          )}
        </ul>`
        : html`<p class="fw-why" id="pcopy-none">${none}</p>`
    }
    <div class="ddns-actions">
      <button type="button" class="btn-pill-toggle" id="pcopy-now" title="${whyNot}" ${whyNot ? 'disabled' : ''}>
        ${t('pcopy.now', 'Copy now')}
      </button>
    </div>
    ${earlier(st, looked)}
    <div class="fw-error" id="pcopy-error" role="alert" hidden></div>`;
  mount.hidden = false;
  const $ = (id) => /** @type {any} */ (mount.querySelector(`#${id}`));
  const fail = (e) => {
    $('pcopy-error').textContent = e instanceof Error ? e.message : String(e);
    $('pcopy-error').hidden = false;
  };
  $('pcopy-now').addEventListener('click', async () => {
    $('pcopy-now').disabled = true;
    try {
      await renderPoolCopyCard(mount, { ...st, ...(await api.post('/api/system/settings-copy/now', {})) }, looked);
    } catch (e) {
      fail(e);
      $('pcopy-now').disabled = false;
    }
  });
  $('pcopy-look').addEventListener('click', async () => {
    $('pcopy-look').disabled = true;
    $('pcopy-look').textContent = t('pcopy.looking', 'Looking…');
    try {
      const { found } = await api.post('/api/system/settings-copy/look', {});
      await renderPoolCopyCard(mount, { ...st, done: {}, found }, true);
    } catch (e) {
      fail(e);
      $('pcopy-look').disabled = false;
      $('pcopy-look').textContent = t('pcopy.look', 'Look on the drives');
    }
  });
  let chosen = null;
  mount.querySelectorAll('.pcopy-bring').forEach((b) =>
    b.addEventListener('click', () => {
      chosen = (st.found || []).find((c) => c.key === /** @type {HTMLElement} */ (b).dataset.key);
      $('pcopy-restore-note').textContent = t(
        'pcopy.restore_note',
        "This replaces the settings this Kiboto has now with those of {name}. Today's settings are saved first. Kiboto then starts again, and you sign in with a password you used on {name}.",
        { name: chosen.name }
      );
      $('pcopy-restore-label').textContent = t('pcopy.restore_key', 'The recovery key of {name}', {
        name: chosen.name,
      });
      $('pcopy-restore').hidden = false;
      $('pcopy-restore-key').focus();
    })
  );
  $('pcopy-restore-cancel').addEventListener('click', () => {
    $('pcopy-restore').hidden = true;
    $('pcopy-restore-key').value = '';
  });
  $('pcopy-restore').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('pcopy-error').hidden = true;
    $('pcopy-restore-go').disabled = true;
    try {
      const back = await api.post('/api/system/settings-copy/restore', {
        key: chosen.key,
        recovery_key: $('pcopy-restore-key').value.trim(),
      });
      $('pcopy-restore').hidden = true;
      $('pcopy-restore-done').textContent = t(
        'pcopy.restore_done',
        'The settings of {name} are coming back. Kiboto is starting again; sign in with a password you used there.',
        { name: back.name || chosen.name }
      );
      $('pcopy-restore-done').hidden = false;
    } catch (err) {
      fail(err);
      $('pcopy-restore-go').disabled = false;
    }
  });
  return st;
}
