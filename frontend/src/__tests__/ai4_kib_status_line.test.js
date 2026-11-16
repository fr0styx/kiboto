/** AI 4: Kib's status line answers "is Kib ready, and what can it read" in one line. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { kibState, kibStatusHtml, renderKibStatusLine } from '../components/management/kib-status-line.js';
import { kibStatusActions, bindStartOver } from '../components/management/ai.js';
import { showConfirmToast } from '../toast.js';
import { api } from '../api.js';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

const ready = { enabled: true, watched_paths: ['/mnt/user/docs', '/mnt/user/photos'], indexed_count: 12480, sync_progress: { state: 'idle' }, learning_results: { kib_status: 'Idle' }, standby_guard: { deferred_queue_count: 0 } };
const line = (res) => { const s = kibState(res); return [s.key, s.icon, s.title, s.second, s.act]; };

describe('Kib status line (AI 4)', () => {
  beforeEach(() => { document.body.innerHTML = '<div id="kib-status-mount"></div>'; vi.clearAllMocks(); });
  afterEach(() => vi.restoreAllMocks());

  it('says ready, with the folders and files it knows', () => {
    expect(line(ready)).toEqual(['ready', '✓', 'Kib is ready', 'Kib can read 2 folders. It knows 12480 files.', '']);
    expect(kibState({ ...ready, watched_paths: ['/a'], indexed_count: 1 }).second).toBe('Kib can read 1 folder. It knows 1 file.');
    expect(kibState({ ...ready, indexed_count: undefined, index_stats: { total_files: 3 } }).second).toContain('It knows 3 files.');
  });

  it('names each other state, in the report\'s order', () => {
    expect(line({ ...ready, enabled: false })).toEqual(['off', '○', 'Kib is off', 'Kib does not read your files. Chat and search answer from what it already knows.', 'on']);
    expect(line({ ...ready, sync_progress: { state: 'running', indexed_files: 1200, skipped_unchanged: 34 } }).slice(2)).toEqual(['Kib is reading your files: 1,234 so far', 'You can keep asking.', 'pause']);
    expect(kibState({ ...ready, sync_progress: { state: 'running', indexed_files: 10, total_files: 50 } }).title).toBe('Kib is reading your files: 10 of 50');
    expect(line({ ...ready, sync_state: 'paused', sync_progress: undefined }).slice(2)).toEqual(['Reading is paused', 'Kib still answers from what it knows.', 'resume']);
    expect(line({ ...ready, watched_paths: [] }).slice(3)).toEqual(['No folder is chosen, so Kib reads nothing.', 'folders']);
    expect(kibState({ ...ready, watched_paths: undefined }).key).toBe('look');
    expect(kibState({ ...ready, learning_results: { kib_status: 'Paused', resume_time: '01:00', schedule_time_zone: 'America/Puerto_Rico' } }).title).toBe('Kib reads again at 01:00 (America/Puerto_Rico)');
    expect(kibState({ ...ready, learning_results: { kib_status: 'Paused', resume_time: '01:00' } }).title).toBe('Kib reads again at 01:00');
    expect(line({ ...ready, standby_guard: { deferred_queue_count: 2 } }).slice(2)).toEqual(['Kib is waiting for a drive to wake: 2 folders', 'Kib does not wake drives to read your files.', '']);
    expect(line({ ...ready, learning_results: { failed_count: 12 } }).slice(3)).toEqual(['12 files could not be read.', 'why']);
    expect(kibState({}).key).toBe('look');
  });

  it('draws words and an icon, and a button only when one fits', () => {
    expect(kibStatusHtml(ready)).not.toContain('<button');
    const html = kibStatusHtml({ ...ready, enabled: false });
    expect(html).toContain('role="status"');
    expect(html).toContain('data-kibs-act="on"');
    expect(html).toContain('>Turn on</button>');
  });

  it('wires the button to the page\'s action', () => {
    const on = vi.fn();
    const mount = document.getElementById('kib-status-mount');
    renderKibStatusLine(mount, { ...ready, enabled: false }, { on });
    mount.querySelector('button').click();
    expect(on).toHaveBeenCalledTimes(1);
    renderKibStatusLine(mount, { ...ready, enabled: false }); // no action given: the button does nothing
    mount.querySelector('button').click();
    renderKibStatusLine(null, ready);
    renderKibStatusLine(mount, ready, { on });
    expect(mount.querySelector('button')).toBeNull();
  });

  it('the page\'s actions pause, continue, show why, turn on and go to the folders', async () => {
    document.body.insertAdjacentHTML('beforeend', '<div><span id="ai-watched-dropdown-summary"></span></div><div id="ai-learning-results-panel"></div>');
    const post = vi.spyOn(api, 'post').mockResolvedValue({});
    const put = vi.spyOn(api, 'put').mockResolvedValue({});
    vi.spyOn(api, 'get').mockResolvedValue({});
    Element.prototype.scrollIntoView = vi.fn();
    const a = kibStatusActions();
    await a.pause();
    expect(post).toHaveBeenCalledWith('/api/media/index/control', { action: 'pause' });
    await a.resume();
    expect(post).toHaveBeenCalledWith('/api/media/index/control', { action: 'resume' });
    await a.stop();
    expect(post).toHaveBeenCalledWith('/api/media/index/control', { action: 'stop' });
    await a.why();
    await a.on();
    expect(put).toHaveBeenCalledWith('/api/media/config', { enabled: true });
    a.folders();
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it('while reading or paused, Cancel reading sits next to Pause or Continue', () => {
    const acts = { pause: vi.fn(), stop: vi.fn() };
    const mount = document.getElementById('kib-status-mount');
    renderKibStatusLine(mount, { ...ready, sync_progress: { state: 'running' } }, acts);
    const btns = [...mount.querySelectorAll('button')];
    expect(btns.map((b) => b.textContent)).toEqual(['Pause', 'Cancel reading']);
    btns[1].click();
    expect(acts.stop).toHaveBeenCalled();
    expect(kibStatusHtml({ ...ready, sync_progress: { state: 'paused' } })).toContain('Cancel reading');
    expect(kibStatusHtml(ready)).not.toContain('Cancel reading');
  });

  it('"Forget everything and start over…" asks first, with its own words', () => {
    document.body.innerHTML = '<button data-kib-flush>Forget everything and start over…</button>';
    bindStartOver();
    bindStartOver();
    document.querySelector('[data-kib-flush]').click();
    expect(showConfirmToast).toHaveBeenCalledTimes(1);
    expect(showConfirmToast.mock.calls[0][0]).toBe('Forget everything and start over?');
    expect(showConfirmToast.mock.calls[0][4].okText).toBe('Forget and start over');
  });
});
