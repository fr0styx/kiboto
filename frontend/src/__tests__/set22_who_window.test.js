import { describe, it, expect, vi, beforeEach } from 'vitest';

const get = vi.fn();
const put = vi.fn();
vi.mock('../api.js', () => ({ api: { get, put } }));
const showToast = vi.fn();
vi.mock('../toast.js', () => ({ showToast }));
const sw = await import('../components/share-who.js');

const PEOPLE = [
  { username: 'owner', name: 'Owner', role: 'superadmin', admin: true, level: 'write' },
  { username: 'anna', name: 'Anna', role: 'share_user', admin: false, level: 'write' },
  { username: 'gus', name: 'Gus', role: 'guest', admin: false, level: 'write' },
];

describe('who can open it, per folder (SET-22, Shares 2)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('administrators as they are, a choice for everyone else, a guest views at most', () => {
    document.body.innerHTML = `<ul>${sw.whoRowsHtml(PEOPLE)}</ul>`;
    expect(document.body.textContent).toContain('Can view and change (administrator)');
    expect(document.querySelector('[data-who-user="owner"]')).toBeNull();
    expect(/** @type {HTMLSelectElement} */ (document.querySelector('[data-who-user="anna"]')).value).toBe('write');
    const gus = /** @type {HTMLSelectElement} */ (document.querySelector('[data-who-user="gus"]'));
    expect([...gus.options].map((o) => o.value)).toEqual(['none', 'read']);
    expect(gus.value).toBe('read');
  });

  it('saving keeps every other folder as it was', () => {
    const access = {
      shares: [
        { name: 'photos', users: { anna: 'read' } },
        { name: 'media', users: { ben: 'write' }, default: 'read' },
      ],
    };
    expect(sw.savedWith(access, 'photos', { anna: 'write', gus: 'none' })).toEqual({
      shares: {
        photos: { users: { anna: 'write', gus: 'none' } },
        media: { users: { ben: 'write' }, default: 'read' },
      },
    });
  });

  it('the window saves the choices and the card refreshes', async () => {
    get.mockImplementation(async (url) =>
      url.endsWith('/who')
        ? { host: '', shares: [{ name: 'photos', people: PEOPLE }] }
        : { shares: [{ name: 'photos', users: {} }] }
    );
    put.mockResolvedValue({});
    HTMLDialogElement.prototype.showModal = vi.fn();
    HTMLDialogElement.prototype.close = vi.fn();
    const onSaved = vi.fn();
    const done = sw.openWhoWindow('photos', onSaved);
    await vi.waitFor(() => expect(document.getElementById('who-window')).not.toBeNull());
    /** @type {HTMLSelectElement} */ (document.querySelector('#who-window [data-who-user="anna"]')).value = 'read';
    /** @type {HTMLElement} */ (document.querySelector('[data-who-save]')).click();
    expect(await done).toBe(true);
    expect(put).toHaveBeenCalledWith('/api/storage/share-access', {
      shares: { photos: { users: { anna: 'read', gus: 'read' } } },
    });
    expect(onSaved).toHaveBeenCalled();
    expect(document.getElementById('who-window')).toBeNull();
  });
});
