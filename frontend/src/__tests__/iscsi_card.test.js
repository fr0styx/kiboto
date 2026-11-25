// Network services: "Disks for other computers (iSCSI)" (owner's decision, 19 Nov 2026).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '../api.js';
import { showToast } from '../toast.js';
import { renderIscsiCard, resetIscsiCardForTesting, iscsiStatus } from '../components/management/iscsi-card.js';

vi.mock('../toast.js', async (orig) => ({ ...(await orig()), showToast: vi.fn() }));

const DISK = {
  id: 'd1',
  name: 'vm-disk',
  iqn: 'iqn.2026-11.net.kiboto:nas:vm-disk',
  size_gb: 200,
  folder: '/mnt/user/iscsi',
  file: '/mnt/user/iscsi/vm-disk.iscsi.img',
  file_there: true,
  used_bytes: 5 * 1024 ** 3,
  user: 'ana',
  allow: '',
};
const view = (over = {}) => ({
  enabled: true,
  running: true,
  port: 3260,
  error: '',
  max_disks: 8,
  max_gb: 65536,
  disks: [DISK],
  ...over,
});
const flush = () => new Promise((r) => setTimeout(r, 0));
const card = () => document.getElementById('iscsi-card');
const press = async (selector) => {
  card().querySelector(selector).click();
  await flush();
  await flush();
};

describe('disks for other computers', () => {
  beforeEach(() => {
    resetIscsiCardForTesting();
    document.body.innerHTML = '<div id="network-services-grid"></div>';
  });
  afterEach(() => {
    resetIscsiCardForTesting();
    vi.restoreAllMocks();
    vi.mocked(showToast).mockClear();
    document.body.innerHTML = '';
  });

  it('says how the service stands', () => {
    expect(iscsiStatus(null)).toBe('Off.');
    expect(iscsiStatus(view({ enabled: false }))).toBe('Off.');
    expect(iscsiStatus(view({ disks: [] }))).toBe('On. Add a disk to start the service.');
    expect(iscsiStatus(view())).toBe('Answers on port 3260.');
    expect(iscsiStatus(view({ running: false }))).toBe(
      'Not running. Port 3260 may be in use by another program on this NAS.'
    );
  });

  it('says the real reason when the service cannot run', () => {
    expect(iscsiStatus(view({ running: false, why: 'engine' }))).toMatch(/cannot reach the app engine/);
    expect(iscsiStatus(view({ running: false, why: 'folder' }))).toMatch(/folder is not one the service can be given/);
    expect(iscsiStatus(view({ running: false, why: 'down' }))).toMatch(/Port 3260 may be in use/);
  });

  it('says it is not on Kiboto OS yet, and the switch cannot be pressed', async () => {
    const notYet = view({ enabled: false, running: false, disks: [], why: 'not_yet' });
    expect(iscsiStatus(notYet)).toBe('This is not available on Kiboto OS yet.');
    vi.spyOn(api, 'get').mockResolvedValue(notYet);
    await renderIscsiCard();
    expect(card().querySelector('#iscsi-status').textContent).toBe('This is not available on Kiboto OS yet.');
    expect(card().querySelector('#iscsi-toggle').disabled).toBe(true);
  });

  it('leaves the switch usable everywhere else', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view({ enabled: false, disks: [] }));
    await renderIscsiCard();
    expect(card().querySelector('#iscsi-toggle').disabled).toBe(false);
  });

  it('is hidden from anyone the server refuses, and needs its place on the page', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('403'));
    expect(await renderIscsiCard()).toBe(false);
    expect(card().hidden).toBe(true);
    document.body.innerHTML = '';
    expect(await renderIscsiCard()).toBe(false);
  });

  it('is off until turned on', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view({ enabled: false, running: false, disks: [] }));
    const put = vi.spyOn(api, 'put').mockResolvedValue(view({ running: false, disks: [] }));
    expect(await renderIscsiCard()).toBe(true);
    await renderIscsiCard(); // drawn again: one card, bound once
    expect(document.querySelectorAll('#iscsi-card').length).toBe(1);
    expect(card().textContent).toContain('Disks for other computers (iSCSI)');
    expect(card().querySelector('#iscsi-status').textContent).toBe('Off.');
    expect(card().querySelector('#iscsi-add')).toBe(null);
    expect(card().querySelector('#iscsi-toggle').getAttribute('aria-pressed')).toBe('false');
    await press('#iscsi-toggle');
    expect(put).toHaveBeenCalledWith('/api/iscsi/enabled', { enabled: true });
    expect(showToast).toHaveBeenCalledWith('iSCSI is on.', 'success');
    expect(card().querySelector('#iscsi-status').textContent).toBe('On. Add a disk to start the service.');
    expect(card().textContent).toContain('No disks yet.');
    put.mockResolvedValue(view({ enabled: false, running: false, disks: [] }));
    await press('#iscsi-toggle');
    expect(put).toHaveBeenLastCalledWith('/api/iscsi/enabled', { enabled: false });
    expect(showToast).toHaveBeenLastCalledWith('iSCSI is off. No disk is offered.', 'success');
  });

  it('lists a disk with what the other computer needs', async () => {
    const limited = {
      ...DISK,
      id: 'd2',
      name: 'only-me',
      allow: '192.168.1.20',
      file_there: false,
      iqn: 'iqn.2026-11.net.kiboto:nas:only-me',
    };
    vi.spyOn(api, 'get').mockResolvedValue(view({ disks: [DISK, limited] }));
    await renderIscsiCard();
    const first = card().querySelector('[data-iscsi-row="d1"]').textContent;
    expect(first).toContain('vm-disk');
    expect(first).toMatch(/200 GB, 5(\.0)? GB written so far/);
    expect(first).toContain('Signs in as ana');
    expect(first).toContain('iqn.2026-11.net.kiboto:nas:vm-disk');
    expect(first).not.toContain('only from');
    const second = card().querySelector('[data-iscsi-row="d2"]').textContent;
    expect(second).toContain('only from 192.168.1.20');
    expect(second).toContain('Its file is not there: /mnt/user/iscsi/vm-disk.iscsi.img');
    expect(card().textContent).toContain('connect to this NAS');
    expect(card().querySelector('#iscsi-status').textContent).toBe('Answers on port 3260.');
  });

  it('adds a disk from the form and never shows a password again', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view({ disks: [] }));
    const post = vi.spyOn(api, 'post').mockResolvedValue(view());
    await renderIscsiCard();
    await press('#iscsi-add');
    const form = card().querySelector('form[data-iscsi-form="new"]');
    const q = (name) => form.querySelector(`[name="${name}"]`);
    expect(form.textContent).toContain('Saving restarts the service');
    q('name').value = ' vm-disk ';
    q('size').value = '200';
    q('folder').value = ' /mnt/user/iscsi ';
    q('user').value = 'ana';
    q('secret').value = 'secretsecret12';
    q('allow').value = '';
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(post).toHaveBeenCalledWith('/api/iscsi/disks', {
      name: 'vm-disk',
      size_gb: 200,
      folder: '/mnt/user/iscsi',
      user: 'ana',
      secret: 'secretsecret12',
      allow: '',
    });
    expect(showToast).toHaveBeenCalledWith('Saved.', 'success');
    expect(card().querySelector('form')).toBe(null);
    expect(card().innerHTML).not.toContain('secretsecret12');
  });

  it('changes a disk: its name and folder stay, the password field starts empty', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view());
    const put = vi.spyOn(api, 'put').mockResolvedValue(view({ disks: [{ ...DISK, size_gb: 300 }] }));
    await renderIscsiCard();
    await press('[data-iscsi-act="edit"]');
    const form = card().querySelector('form[data-iscsi-form="d1"]');
    expect(form.querySelector('[name="name"]').disabled).toBe(true);
    expect(form.querySelector('[name="folder"]').disabled).toBe(true);
    expect(form.querySelector('[name="size"]').min).toBe('200'); // it can only grow
    expect(form.querySelector('[name="secret"]').value).toBe('');
    expect(form.querySelector('[name="secret"]').placeholder).toBe('Saved; type a new one to change it');
    form.querySelector('[name="size"]').value = '300';
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(put.mock.calls[0][0]).toBe('/api/iscsi/disks/d1');
    expect(put.mock.calls[0][1]).toMatchObject({ size_gb: 300, secret: '', user: 'ana' });
    expect(card().textContent).toContain('300 GB');
    await press('[data-iscsi-act="edit"]');
    await press('[data-iscsi-act="edit"]'); // pressed again: the form closes
    expect(card().querySelector('form')).toBe(null);
  });

  it('keeps the form and says what is wrong when the server refuses, stays quiet on Cancel', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view({ disks: [] }));
    const post = vi
      .spyOn(api, 'post')
      .mockRejectedValue(new Error('The password must be 12 to 16 characters, without spaces.'));
    await renderIscsiCard();
    await press('#iscsi-add');
    let form = card().querySelector('form');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    form = card().querySelector('form');
    expect(form.querySelector('[role="alert"]').textContent).toBe(
      'The password must be 12 to 16 characters, without spaces.'
    );
    expect(form.querySelector('[role="alert"]').hidden).toBe(false);
    post.mockRejectedValue(Object.assign(new Error('cancelled'), { error: 'cancelled' }));
    form.querySelector('[role="alert"]').hidden = true;
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(form.querySelector('[role="alert"]').hidden).toBe(true); // the person said no to the confirm: nothing is wrong
    form.querySelector('button[type="button"]').click();
    expect(card().querySelector('form')).toBe(null);
  });

  it('removes a disk from the list and says its file stays', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view());
    const del = vi.spyOn(api, 'delete').mockResolvedValue(view({ disks: [] }));
    await renderIscsiCard();
    await press('[data-iscsi-act="edit"]');
    await press('[data-iscsi-act="remove"]');
    expect(del).toHaveBeenCalledWith('/api/iscsi/disks/d1');
    expect(showToast).toHaveBeenCalledWith('Removed from the list. Its file is still in its folder.', 'success');
    expect(card().querySelector('[data-iscsi-row="d1"]')).toBe(null);
    expect(card().querySelector('form')).toBe(null);
  });

  it('says why a change did not happen', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view());
    vi.spyOn(api, 'delete').mockRejectedValue(new Error('offline'));
    vi.spyOn(api, 'put').mockRejectedValue(Object.assign(new Error('cancelled'), { error: 'cancelled' }));
    await renderIscsiCard();
    await press('[data-iscsi-act="remove"]');
    expect(showToast).toHaveBeenCalledWith("That didn't work: offline", 'error');
    vi.mocked(showToast).mockClear();
    await press('#iscsi-toggle'); // cancelled at the confirm: no toast, still on
    expect(showToast).not.toHaveBeenCalled();
    expect(card().querySelector('#iscsi-toggle').getAttribute('aria-pressed')).toBe('true');
  });

  it('offers no more disks than there can be', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view({ max_disks: 1 }));
    await renderIscsiCard();
    expect(card().querySelector('#iscsi-add')).toBe(null);
  });
});
