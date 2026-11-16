import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
const { showToast } = await import('../toast.js');
const { organizeResultToasts } = await import('../components/file-manager.js');

describe('Organize Media says what really happened (SET-28 Files 2)', () => {
  beforeEach(() => vi.mocked(showToast).mockClear());

  it('all sorted: one success message with the server count', () => {
    organizeResultToasts({ success_count: 3, kept_count: 0, failed_count: 0 }, 5);
    expect(showToast).toHaveBeenCalledTimes(1);
    expect(showToast).toHaveBeenCalledWith('Media sorted: 3 files.', 'success');
  });

  it('kept and failed files are named, and a failed link says nothing moved', () => {
    organizeResultToasts({ success_count: 1, kept_count: 2, failed_count: 1, failures: [{ code: 'no_link' }] }, 4);
    const calls = vi.mocked(showToast).mock.calls;
    expect(calls[0]).toEqual(['Media sorted: 1 file.', 'warning']);
    expect(calls[1]).toEqual(['2 files were already there and were kept.', 'warning']);
    expect(calls[2][0]).toBe('1 file could not be sorted. A link is not possible there; nothing was moved.');
    expect(calls[2][1]).toBe('error');
  });

  it('without a count from the server it falls back to the plan', () => {
    organizeResultToasts({}, 2);
    expect(showToast).toHaveBeenCalledWith('Media sorted: 2 files.', 'success');
  });
});
