import { describe, it, expect, vi, beforeEach } from 'vitest';

const get = vi.fn();
const post = vi.fn();
vi.mock('../api.js', () => ({ api: { get, post } }));
const showToast = vi.fn();
vi.mock('../toast.js', () => ({ showToast }));
const offerRecoveryKit = vi.fn();
vi.mock('../components/offsite-backup.js', () => ({ offerRecoveryKit }));
const openProtectGuide = vi.fn();
vi.mock('../components/protect-nas.js', () => ({ openProtectGuide }));

const bv = await import('../components/backup-verdict.js');
const WHEN = 1800000000;

describe('Are your files safe? (SET-21)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML =
      '<section id="s" hidden><div id="m"></div></section><h3 id="offsite-title"></h3><div id="backup-jobs-mount"></div>';
  });

  it('a word with an icon for each level, and one sentence', () => {
    expect(bv.verdictWord('fine')).toEqual(['✓', 'Fine']);
    expect(bv.verdictWord('failed')[1]).toBe('Failed');
    expect(bv.verdictWord('look')[1]).toBe('Needs a look');
    expect(bv.verdictWord('none')[1]).toBe('Not protected yet');
    expect(bv.verdictSentence({ level: 'fine', newest: { name: 'Office disk', when: WHEN } })).toContain(
      'on "Office disk"'
    );
    expect(bv.verdictSentence({ level: 'none', newest: null })).toBe('No copy of your files outside this Kiboto yet.');
    expect(bv.verdictSentence({ level: 'look', newest: null })).toBe('No good copy outside this Kiboto yet.');
  });

  it('each line says what is wrong and offers one button', () => {
    const lines = [
      [{ kind: 'failed', name: 'B2', id: 'r1', engine: 'offsite' }, 'B2: the last backup failed.', 'backup'],
      [{ kind: 'late', name: 'B2', id: 'r1', engine: 'offsite', since: null }, 'B2: no backup yet.', 'backup'],
      [{ kind: 'late', name: 'Copy', id: null, engine: 'copy', since: WHEN }, 'Copy: no backup since', 'open'],
      [{ kind: 'same_disk', name: 'Here', id: 'r2' }, 'same disk', 'open'],
      [{ kind: 'here_only', name: 'Here', id: 'r2' }, 'a fire or a theft', 'open'],
      [{ kind: 'kit', name: 'B2', id: 'r1' }, 'recovery kit', 'kit'],
      [{ kind: 'unreadable', name: 'B2', id: 'r1', count: 2 }, '2 files could not be read', 'open'],
      [{ kind: 'drill', name: 'B2', id: 'r1' }, 'test restore failed', 'open'],
      [{ kind: 'snap_failed', name: 'photos', engine: 'snapshot' }, 'could not be made', 'open'],
      [{ kind: 'snap_late', name: 'photos', engine: 'snapshot' }, 'none made lately', 'open'],
      [{ kind: 'check_late', name: 'tank', engine: 'check' }, 'monthly disk check', 'open'],
      [{ kind: 'check_errors', name: 'tank', engine: 'check', count: 1 }, 'found 1 error.', 'open'],
      [{ kind: 'other', name: 'X' }, 'X', 'open'],
    ];
    for (const [issue, text, act] of lines) {
      expect(bv.issueText(issue)).toContain(text);
      expect(bv.issueAction(issue).act).toBe(act);
    }
    expect(bv.issueText({ kind: 'unreadable', name: 'B2' })).toContain('0 files');
    expect(bv.OPENS.snapshot).toBe('snapshot-schedules-mount');
  });

  it('shows the answer and acts on a line', async () => {
    get.mockResolvedValue({
      level: 'failed',
      newest: { name: 'B2', when: WHEN },
      issues: [
        { kind: 'failed', name: 'B2', id: 'r1', engine: 'offsite' },
        { kind: 'kit', name: 'B2', id: 'r1', engine: 'offsite' },
        { kind: 'late', name: 'Copy', id: null, engine: 'copy', since: WHEN },
      ],
    });
    const mount = /** @type {HTMLElement} */ (document.getElementById('m'));
    Element.prototype.scrollIntoView = vi.fn();
    await bv.renderVerdict(mount);
    expect(document.getElementById('s')?.hasAttribute('hidden')).toBe(false);
    expect(mount.querySelector('.bk-verdict-line')?.textContent).toContain('Failed.');
    const buttons = mount.querySelectorAll('button[data-bk-act]');
    post.mockResolvedValueOnce({});
    /** @type {HTMLElement} */ (buttons[0]).click();
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/offsite/repos/r1/backup', {}));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Backing up B2 now.', 'success'));
    /** @type {HTMLElement} */ (buttons[1]).click();
    await vi.waitFor(() => expect(offerRecoveryKit).toHaveBeenCalledWith({ id: 'r1' }, expect.any(Function)));
    /** @type {HTMLElement} */ (buttons[2]).click();
    expect(document.getElementById('backup-jobs-mount')?.scrollIntoView).toHaveBeenCalled();
    post.mockRejectedValueOnce(new Error('No such backup.'));
    /** @type {HTMLElement} */ (buttons[0]).click();
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('No such backup.', 'error'));
  });

  it('nothing set up offers to protect; a refusal hides the section', async () => {
    get.mockResolvedValueOnce({ level: 'none', newest: null, issues: [] });
    const mount = /** @type {HTMLElement} */ (document.getElementById('m'));
    await bv.renderVerdict(mount);
    /** @type {HTMLElement} */ (mount.querySelector('[data-bk-act="protect"]')).click();
    await vi.waitFor(() => expect(openProtectGuide).toHaveBeenCalled());
    get.mockRejectedValueOnce(new Error('403'));
    expect(await bv.renderVerdict(mount)).toBeNull();
    expect(document.getElementById('s')?.hasAttribute('hidden')).toBe(true);
    expect(await bv.renderVerdict(null)).toBeNull();
  });
});
