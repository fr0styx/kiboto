// Are your files safe? (SET-21 stage 1, Backup report section 4): the first thing on Backup. One
// word with an icon, one sentence, then only what needs a look, each line with one button.
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { formatDateTime } from '../format.js';

/** [icon, word] for the level: never a colour alone. */
export function verdictWord(level) {
  if (level === 'fine') return ['✓', t('bk.v_fine', 'Fine')];
  if (level === 'failed') return ['✕', t('bk.v_failed', 'Failed')];
  if (level === 'look') return ['!', t('bk.v_look', 'Needs a look')];
  return ['○', t('bk.v_none', 'Not protected yet')];
}

/** The one sentence under the word. */
export function verdictSentence(v) {
  if (v.newest)
    return t('bk.v_newest', 'Newest copy outside this Kiboto: {when}, on "{name}".', {
      when: formatDateTime(v.newest.when * 1000),
      name: v.newest.name,
    });
  if (v.level === 'none') return t('bk.v_nothing', 'No copy of your files outside this Kiboto yet.');
  return t('bk.v_no_good', 'No good copy outside this Kiboto yet.');
}

/** What one line says. */
export function issueText(i) {
  const name = i.name || '';
  switch (i.kind) {
    case 'failed':
      return t('bk.i_failed', '{name}: the last backup failed.', { name });
    case 'late':
      return i.since
        ? t('bk.i_late', '{name}: no backup since {when}.', { name, when: formatDateTime(i.since * 1000) })
        : t('bk.i_never', '{name}: no backup yet.', { name });
    case 'same_disk':
      return t(
        'bk.i_same_disk',
        '{name} is on the same disk as the files it copies: if the disk fails, both are gone.',
        { name }
      );
    case 'here_only':
      return t('bk.i_here', '{name} stays on this Kiboto: a fire or a theft takes both.', { name });
    case 'kit':
      return t(
        'bk.i_kit',
        '{name}: the recovery kit is not saved yet. Without it the backup cannot be opened elsewhere.',
        { name }
      );
    case 'unreadable':
      return t('bk.i_unreadable', '{name}: {n, plural, one {# file} other {# files}} could not be read.', {
        name,
        n: i.count || 0,
      });
    case 'drill':
      return t('bk.i_drill', '{name}: the last test restore failed.', { name });
    case 'snap_failed':
      return t('bk.i_snap_failed', 'Earlier versions of {name}: the last one could not be made.', { name });
    case 'snap_late':
      return t('bk.i_snap_late', 'Earlier versions of {name}: none made lately.', { name });
    case 'check_late':
      return t('bk.i_check_late', '{name}: the monthly disk check has not run lately.', { name });
    case 'check_errors':
      return t('bk.i_check_errors', '{name}: the last disk check found {n, plural, one {# error} other {# errors}}.', {
        name,
        n: i.count || 0,
      });
    default:
      return name;
  }
}

/** The one button for a line: what it does and what it says. */
export function issueAction(i) {
  if ((i.kind === 'failed' || i.kind === 'late') && i.engine === 'offsite' && i.id)
    return { act: 'backup', label: t('bk.a_backup', 'Back up now') };
  if (i.kind === 'kit' && i.id) return { act: 'kit', label: t('bk.a_kit', 'Save the recovery kit') };
  return { act: 'open', label: t('bk.a_open', 'Open') };
}

/** Where "Open" goes for a line: the section that holds what it names. */
export const OPENS = { offsite: 'offsite-title', snapshot: 'snapshot-schedules-mount', check: 'protection-jobs-mount' };

export function verdictHtml(v) {
  const [icon, word] = verdictWord(v.level);
  const lines = (v.issues || [])
    .map((i, n) => {
      const a = issueAction(i);
      return `<li class="bk-issue"><span>${escapeHtml(issueText(i))}</span><button type="button" class="btn-pill-toggle is-small" data-bk-act="${a.act}" data-bk-n="${n}">${escapeHtml(a.label)}</button></li>`;
    })
    .join('');
  const protect =
    v.level === 'none'
      ? `<button type="button" class="btn-pill-toggle is-primary" data-bk-act="protect">${escapeHtml(t('bk.a_protect', 'Protect this Kiboto'))}</button>`
      : '';
  return `<p class="bk-verdict-line is-${escapeHtml(v.level)}"><span class="bk-verdict-icon" aria-hidden="true">${icon}</span><strong>${escapeHtml(word)}.</strong> ${escapeHtml(verdictSentence(v))}</p>
    ${lines ? `<ul class="bk-issues">${lines}</ul>` : ''}${protect}`;
}

/** Fills the mount from the server; the buttons act on the line's backup. */
export async function renderVerdict(mount) {
  if (!mount) return null;
  let v;
  try {
    v = await api.get('/api/system/protection/verdict');
  } catch {
    mount.closest('section')?.setAttribute('hidden', '');
    return null;
  }
  mount.closest('section')?.removeAttribute('hidden');
  mount.innerHTML = verdictHtml(v);
  mount.onclick = async (e) => {
    const b = /** @type {HTMLElement | null} */ (/** @type {HTMLElement} */ (e.target).closest('button[data-bk-act]'));
    if (!b) return;
    const issue = (v.issues || [])[Number(b.dataset.bkN)] || {};
    if (b.dataset.bkAct === 'backup') {
      try {
        await api.post(`/api/offsite/repos/${encodeURIComponent(issue.id)}/backup`, {});
        showToast(t('bk.started', 'Backing up {name} now.', { name: issue.name }), 'success');
      } catch (err) {
        showToast(/** @type {Error} */ (err).message, 'error');
      }
    } else if (b.dataset.bkAct === 'kit') {
      import('./offsite-backup.js')
        .then((m) => m.offerRecoveryKit({ id: issue.id }, () => renderVerdict(mount)))
        .catch(() => {});
    } else if (b.dataset.bkAct === 'protect') {
      import('./protect-nas.js').then((m) => m.openProtectGuide()).catch(() => {});
    } else {
      const target = document.getElementById(OPENS[issue.engine] || 'backup-jobs-mount');
      target?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    }
  };
  return v;
}
