/** AI 3, findings 19 and 20: the Kib page reads what the server really answers. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { learnReason, renderAiLearningResultsData, relearnAiFailedFiles, triggerInPlaceReindex, syncAiWatchedFolders, runAiPathIndex, renderAiWatchedFoldersAndShares } from '../components/management/ai.js';
import { api } from '../api.js';
import { showToast } from '../toast.js';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

const byId = (id) => document.getElementById(id);
const lastToast = () => showToast.mock.calls.at(-1);

describe('Kib re-index and learning results (AI 3)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    document.body.innerHTML = `
      <span id="ai-learn-succeeded-count"></span><span id="ai-learn-failed-count"></span><span id="ai-learn-deferred-count"></span>
      <div id="ai-learn-failed-list"></div><div id="ai-reindex-progress-container" style="display:none"></div>`;
    vi.spyOn(api, 'get').mockResolvedValue({ status: 'complete' });
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it('names why a file could not be read', () => {
    expect(learnReason('parse_error')).toBe('Kib could not open this file.');
    expect(learnReason('error')).toBe('Kib could not open this file.');
    expect(learnReason('')).toBe('Kib could not open this file.');
    expect(learnReason(undefined)).toBe('Kib could not open this file.');
    expect(learnReason('Password protected')).toBe('Password protected');
  });

  it('shows the counts and files under the names the server sends', () => {
    renderAiLearningResultsData({
      succeeded_count: 12, failed_count: 2, deferred_count: 3,
      failed_files: [{ path: '/mnt/user/docs/a.pdf', name: 'a.pdf', reason: 'parse_error' }, { name: 'b.doc', reason: 'Password protected' }],
    });
    expect(byId('ai-learn-succeeded-count').textContent).toBe('12');
    expect(byId('ai-learn-failed-count').textContent).toBe('2');
    expect(byId('ai-learn-deferred-count').textContent).toBe('3');
    const rows = [...byId('ai-learn-failed-list').children].map((r) => r.textContent.replace(/\s+/g, ' ').trim());
    expect(rows).toEqual(['/mnt/user/docs/a.pdf Kib could not open this file.', 'b.doc Password protected']);
    renderAiLearningResultsData({ deferred_standby_count: 1, failed_files: [{ file_path: '/x', error: 'old' }, {}] });
    expect(byId('ai-learn-deferred-count').textContent).toBe('1');
    expect(byId('ai-learn-failed-list').textContent).toContain('/x');
    renderAiLearningResultsData({});
    expect(byId('ai-learn-deferred-count').textContent).toBe('0');
  });

  it('Try again reports what was recovered and what is left', async () => {
    vi.spyOn(api, 'post').mockResolvedValueOnce({ recovered: 4, failed_count: 1 }).mockResolvedValueOnce({ relearned: 2, still_failed: 0 }).mockResolvedValueOnce({});
    await relearnAiFailedFiles();
    expect(lastToast()).toEqual(['Relearned 4 files (1 left).', 'success']);
    await relearnAiFailedFiles();
    expect(lastToast()).toEqual(['Relearned 2 files (0 left).', 'success']);
    await relearnAiFailedFiles();
    expect(lastToast()).toEqual(['Relearned 0 files (0 left).', 'success']);
  });

  it('a re-index that started, is already running, or did not start says so', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ status: 'started', model: 'm' });
    await triggerInPlaceReindex();
    expect(lastToast()).toEqual(['In-place re-indexing started in background', 'success']);
    expect(byId('ai-reindex-progress-container').style.display).toBe('block');
    await vi.advanceTimersByTimeAsync(1600); // the poll ends on a finished run
    post.mockResolvedValueOnce({ status: 'in_progress' });
    await triggerInPlaceReindex();
    expect(lastToast()).toEqual(['Kib is already rebuilding its search index.', 'info']);
    await vi.advanceTimersByTimeAsync(1600);
    post.mockResolvedValueOnce({ status: 'busy', detail: 'The model is not answering' });
    await triggerInPlaceReindex();
    expect(lastToast()).toEqual(['Failed to start re-indexing: The model is not answering', 'error']);
    expect(byId('ai-reindex-progress-container').style.display).toBe('none');
    post.mockResolvedValueOnce({ status: 'odd' });
    await triggerInPlaceReindex();
    expect(lastToast()).toEqual(['Failed to start re-indexing: odd', 'error']);
    post.mockResolvedValueOnce(null);
    await triggerInPlaceReindex();
    expect(lastToast()).toEqual(['Failed to start re-indexing: ?', 'error']);
    post.mockRejectedValueOnce(new Error('denied'));
    await triggerInPlaceReindex();
    expect(lastToast()).toEqual(['Failed to start re-indexing: denied', 'error']);
  });

  it('one reading job: started, already running, or finished at once (finding 22)', async () => {
    document.body.insertAdjacentHTML('beforeend', '<div id="ai-index-run-feedback"></div><button id="btn-ai-run-index"></button>');
    renderAiWatchedFoldersAndShares(['/mnt/user/docs', '/mnt/user/photos'], []);
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ status: 'started', sync_progress: { state: 'running' } });
    await syncAiWatchedFolders();
    expect(byId('ai-index-run-feedback').textContent).toBe('🔄 Kib started reading 2 folders. Sleeping drives are left asleep.');
    expect(post.mock.calls[0][1].background).toBe(true);
    renderAiWatchedFoldersAndShares(['/mnt/user/docs', '/mnt/user/photos'], []); // the status refresh reloads the list
    post.mockResolvedValueOnce({ status: 'already_running', state: 'running' });
    await syncAiWatchedFolders();
    expect(lastToast()).toEqual(['Kib is already reading. It goes on with what it was doing.', 'info']);
    post.mockResolvedValueOnce({ status: 'started' });
    await runAiPathIndex('/mnt/user/docs');
    expect(post.mock.calls.at(-1)[1].background).toBe(true);
    expect(byId('ai-index-run-feedback').textContent).toBe('🔄 Kib started reading /mnt/user/docs. Sleeping drives are left asleep.');
    post.mockResolvedValueOnce({ status: 'ok', indexed: 3, skipped_unchanged: 1, deferred_standby: 2 });
    await runAiPathIndex(['/a', '/b']);
    expect(byId('ai-index-run-feedback').textContent).toBe('✓ Indexed 3 file(s), 1 unchanged (2 deferred to protect sleeping drives).');
    post.mockResolvedValueOnce({ status: 'ok', indexed_files: 1 });
    await runAiPathIndex('/a');
    expect(byId('ai-index-run-feedback').textContent).toBe('✓ Indexed 1 file(s) (0 unchanged) on /a.');
    renderAiWatchedFoldersAndShares(['/mnt/user/docs'], []);
    post.mockResolvedValueOnce({ status: 'started' });
    await syncAiWatchedFolders();
    expect(byId('ai-index-run-feedback').textContent).toBe('🔄 Kib started reading /mnt/user/docs. Sleeping drives are left asleep.');
    await vi.advanceTimersByTimeAsync(3000);
  });
});
