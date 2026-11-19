// Shared folders: "Old files move to the slower drives" (data tiering, owner's decisions 19 Nov 2026).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '../api.js';
import { showToast } from '../toast.js';
import {
  renderTieringCard,
  resetTieringCardForTesting,
  tieringStatus,
  tieringLastRun,
  tieringWhy,
} from '../components/tiering-card.js';

vi.mock('../toast.js', async (orig) => ({ ...(await orig()), showToast: vi.fn() }));

const DAY = 86400;
const FILMS = {
  name: 'Films',
  why: '',
  enabled: true,
  days: 90,
  since: 1_700_000_000,
  learning_until: 1_700_000_000 + 90 * DAY,
  learning: false,
  last_run: null,
  watching: true,
};
const view = (folders, over = {}) => ({
  folders,
  run_at: '03:00',
  default_days: 90,
  min_days: 7,
  max_days: 3650,
  moving: false,
  watch_error: '',
  ...over,
});
const run = (over = {}) => ({
  started: 1_763_600_000,
  ended: 1_763_600_300,
  how: 'schedule',
  learning: false,
  more: false,
  chosen: 3,
  moved: 3,
  bytes: 5 * 1024 ** 3,
  counts: { moved: 3 },
  errors: [],
  why: '',
  ...over,
});
const flush = () => new Promise((r) => setTimeout(r, 0));
const card = () => document.getElementById('tiering-card');
const press = async (selector) => {
  card().querySelector(selector).click();
  await flush();
  await flush();
};

describe('old files move to the slower drives', () => {
  beforeEach(() => {
    resetTieringCardForTesting();
    document.body.innerHTML = '<div id="pane"><div id="shares"></div><details id="shares-advanced"></details></div>';
  });
  afterEach(() => {
    resetTieringCardForTesting();
    vi.restoreAllMocks();
    vi.mocked(showToast).mockClear();
    document.body.innerHTML = '';
  });

  it('says how a folder stands', () => {
    const v = view([FILMS]);
    expect(tieringStatus({ name: 'Films', why: '', enabled: false }, v)).toBe('Off.');
    expect(tieringStatus(FILMS, v)).toBe('On. Files not opened for 90 days move at 03:00.');
    expect(tieringStatus({ ...FILMS, learning: true }, v)).toMatch(
      /^Watching which files are opened\. Nothing moves before .*2024.*\.$/
    );
    expect(tieringStatus({ ...FILMS, watching: false }, v)).toBe(
      'On, but Kiboto cannot see which files are opened on this system, so nothing moves.'
    );
    expect(tieringStatus({ ...FILMS, last_run: run() }, v)).toMatch(/^Last run .*: 3 files moved \(5(\.0)? GB\)\.$/);
  });

  it('says how the last run went', () => {
    expect(tieringLastRun(run({ moved: 1, counts: { moved: 1, in_use: 2 } }))).toMatch(
      /: 1 file moved \(.*\)\. 2 files were open and stayed\.$/
    );
    expect(tieringLastRun(run({ chosen: 0, moved: 0, bytes: 0 }))).toMatch(/: no file was old enough\.$/);
    expect(tieringLastRun(run({ moved: 0, counts: { already_there: 3 } }))).toMatch(/: nothing moved\.$/);
    expect(tieringLastRun(run({ why: 'full', moved: 2 }))).toMatch(
      /the slower drives are full, so it stopped\. 2 files moved\.$/
    );
    expect(tieringLastRun(run({ why: 'no_start', moved: 0 }))).toMatch(
      /could not start the program that moves the files\.$/
    );
    expect(tieringLastRun(run({ why: 'too_long' }))).toMatch(/took too long and was stopped/);
    expect(tieringLastRun(run({ why: 'not_watching', moved: 0 }))).toMatch(/was not seeing which files are opened\.$/);
    expect(tieringLastRun(run({ errors: [{ file: 'a', why: 'x' }], more: true }))).toMatch(
      /1 file could not be moved\. More files are old than one night moves; the rest follows\.$/
    );
  });

  it('shows the folders that fit, and why the others do not', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(
      view([
        FILMS,
        { name: 'Photos', why: '', enabled: false },
        { name: 'Downloads', why: 'unraid_moves_all', enabled: false },
        { name: 'Games', why: 'unraid_moves_back', enabled: false },
      ])
    );
    expect(await renderTieringCard()).toBe(true);
    expect(card().nextElementSibling.id).toBe('shares-advanced'); // above "Other ways to connect"
    const rows = [...card().querySelectorAll('li[data-tier-row]')];
    expect(rows.map((r) => r.dataset.tierRow)).toEqual(['Films', 'Photos']);
    expect(rows[0].querySelector('[data-tier-act="toggle"]').getAttribute('aria-pressed')).toBe('true');
    expect(rows[0].querySelector('[data-tier-act="run"]')).not.toBeNull();
    expect(rows[1].querySelector('[data-tier-act="run"]')).toBeNull();
    expect(rows[1].querySelector('input').value).toBe('90');
    const unfit = card().querySelector('details');
    expect(unfit.querySelector('summary').textContent).toBe('2 folders do not fit');
    expect(unfit.textContent).toContain(`Downloads: ${tieringWhy('unraid_moves_all')}`);
    expect(unfit.textContent).toContain(`Games: ${tieringWhy('unraid_moves_back')}`);
  });

  it('says so in one sentence where no folder can fit', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(
      view([
        { name: 'Media', why: 'no_merged_folder', enabled: false },
        { name: 'Docs', why: 'no_merged_folder', enabled: false },
      ])
    );
    await renderTieringCard();
    expect(card().querySelector('#tiering-none').textContent).toBe(tieringWhy('no_merged_folder'));
    expect(card().querySelector('details')).toBeNull();
    expect(card().querySelector('li[data-tier-row]')).toBeNull();
  });

  it('turns a folder on with the days typed, and off again', async () => {
    const off = { name: 'Films', why: '', enabled: false };
    vi.spyOn(api, 'get').mockResolvedValue(view([off]));
    const put = vi
      .spyOn(api, 'put')
      .mockResolvedValueOnce(view([{ ...FILMS, days: 30, learning: true }]))
      .mockResolvedValueOnce(view([off]));
    await renderTieringCard();
    card().querySelector('input[data-tier-days]').value = '30';
    await press('[data-tier-act="toggle"]');
    expect(put).toHaveBeenLastCalledWith('/api/tiering/folders/Films', { enabled: true, days: 30 });
    expect(vi.mocked(showToast).mock.calls[0][0]).toBe(
      'On for Films. Kiboto watches the folder for 30 days before it moves anything.'
    );
    expect(card().querySelector('.immich-note').textContent).toMatch(/^Watching which files are opened/);
    expect(card().querySelector('[data-tier-act="run"]')).toBeNull(); // nothing to move while it learns
    await press('[data-tier-act="toggle"]');
    expect(put).toHaveBeenLastCalledWith('/api/tiering/folders/Films', { enabled: false, days: 30 });
    expect(vi.mocked(showToast).mock.calls[1][0]).toBe('Off for Films. Files that have moved stay where they are.');
  });

  it('saves other days for a folder that is on, and only then', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view([FILMS, { name: 'Photos', why: '', enabled: false }]));
    const put = vi.spyOn(api, 'put').mockResolvedValue(view([{ ...FILMS, days: 120 }]));
    await renderTieringCard();
    const [films, photos] = card().querySelectorAll('input[data-tier-days]');
    photos.value = '45';
    photos.dispatchEvent(new Event('change', { bubbles: true }));
    await flush();
    expect(put).not.toHaveBeenCalled();
    films.value = '120';
    films.dispatchEvent(new Event('change', { bubbles: true }));
    await flush();
    await flush();
    expect(put).toHaveBeenCalledWith('/api/tiering/folders/Films', { enabled: true, days: 120 });
    expect(card().querySelector('input[data-tier-days]').value).toBe('120');
  });

  it('moves now when asked, and shows that files are moving', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view([FILMS]));
    const post = vi.spyOn(api, 'post').mockResolvedValue(view([FILMS], { moving: true }));
    await renderTieringCard();
    await press('[data-tier-act="run"]');
    expect(post).toHaveBeenCalledWith('/api/tiering/folders/Films/run', {});
    expect(card().querySelector('#tiering-moving').textContent).toBe('Files are being moved now.');
    expect(card().querySelector('[data-tier-act="run"]')).toBeNull();
  });

  it('says what went wrong, and nothing when the confirmation was cancelled', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view([{ name: 'Films', why: '', enabled: false }]));
    vi.spyOn(api, 'put')
      .mockRejectedValueOnce({ error: 'cancelled' })
      .mockRejectedValueOnce({ error: 'tiering_bad_days', message: 'The number of days must be between 7 and 3650.' });
    await renderTieringCard();
    await press('[data-tier-act="toggle"]');
    expect(showToast).not.toHaveBeenCalled();
    await press('[data-tier-act="toggle"]');
    expect(vi.mocked(showToast).mock.calls[0]).toEqual([
      "That didn't work: The number of days must be between 7 and 3650.",
      'error',
    ]);
  });

  it('stays away for someone who does not manage the storage', async () => {
    vi.spyOn(api, 'get').mockRejectedValue({ status: 403 });
    expect(await renderTieringCard()).toBe(false);
    expect(card().hidden).toBe(true);
    document.body.innerHTML = '<div></div>';
    expect(await renderTieringCard()).toBe(false);
  });
});
