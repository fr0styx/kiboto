import { describe, it, expect, vi, beforeEach } from 'vitest';

const get = vi.fn();
vi.mock('../api.js', () => ({ api: { get } }));
const showBottomSheet = vi.fn();
const showConfirmToast = vi.fn();
vi.mock('../toast.js', () => ({ showBottomSheet, showConfirmToast, showToast: vi.fn() }));

const m = await import('../components/management/delete-person.js');

describe('deleting a person asks about their files (SET-19, Users decision 7)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('each choice has its query and its question', () => {
    expect(m.deleteQuery({ files: 'keep' })).toBe('?files=keep');
    expect(m.deleteQuery({ files: 'delete' })).toBe('?files=delete');
    expect(m.deleteQuery({ files: 'give', to: 'mum & dad' })).toBe('?files=give&give_to=mum%20%26%20dad');
    expect(m.deleteQuery({ files: 'give' })).toBe('?files=give&give_to=');
    expect(m.deleteQuestion({ files: 'delete' }, 'lea')).toContain("can't be undone");
    expect(m.deleteQuestion({ files: 'give', to: 'mum' }, 'lea')).toBe(
      'Delete @lea? Their files go to mum, in a folder named "From lea".'
    );
    expect(m.deleteQuestion({ files: 'keep' }, 'lea')).toContain('renamed');
  });

  it('says what happened to the files', () => {
    expect(m.filesDoneText({ files: 'kept', where: '/pool/homes/lea-former-2026-11-13' })).toBe(
      'Their files are in lea-former-2026-11-13.'
    );
    expect(m.filesDoneText({ files: 'given', to: 'mum' })).toBe('Their files are with mum now.');
    expect(m.filesDoneText({ files: 'deleted' })).toBe('Their files were deleted.');
    expect(m.filesDoneText({ files: 'error', error: 'busy' })).toBe('Their files could not be handled: busy');
    expect(m.filesDoneText({ files: 'error' })).toBe('Their files could not be handled: ');
    expect(m.filesDoneText({ files: 'kept' })).toBe('Their files are in .');
    expect(m.filesDoneText({ files: 'none' })).toBe('');
    expect(m.filesDoneText(undefined)).toBe('');
  });

  it('offers keep, give to each other person, and delete last, in red', async () => {
    get.mockResolvedValue({ users: [{ username: 'lea' }, { username: 'mum' }, { username: 'tom' }] });
    const run = vi.fn();
    await m.askDeletePerson({ id: 'u1', username: 'lea' }, run);
    const { items, title } = showBottomSheet.mock.calls[0][0];
    expect(title).toBe('What happens to the files of lea?');
    expect(items.map((i) => i.label)).toEqual([
      'Keep their files',
      'Give their files to mum',
      'Give their files to tom',
      'Delete their files too',
    ]);
    expect(items[3].destructive).toBe(true);
    items[1].onClick();
    const [, question, onOk, , opts] = showConfirmToast.mock.calls[0];
    expect(question).toContain('Their files go to mum');
    expect(opts.typeToConfirm).toBe('lea');
    onOk();
    expect(run).toHaveBeenCalledWith({ files: 'give', to: 'mum' });
  });

  it('without the list of people, keep and delete still work', async () => {
    get.mockRejectedValue(new Error('403'));
    await m.askDeletePerson({ id: 'u1', username: 'lea' }, vi.fn());
    expect(showBottomSheet.mock.calls[0][0].items.map((i) => i.label)).toEqual([
      'Keep their files',
      'Delete their files too',
    ]);
    get.mockResolvedValue([{ username: 'mum' }]);
    await m.askDeletePerson({ id: 'u1', username: 'lea' }, vi.fn());
    expect(showBottomSheet.mock.calls[1][0].items.length).toBe(3);
  });
});
