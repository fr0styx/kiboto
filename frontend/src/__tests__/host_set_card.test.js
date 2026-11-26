// Kernel, ZFS and Docker (Updates): held, moved only to the versions a Kiboto release was tested with.
import { describe, it, expect, vi, beforeEach } from 'vitest';

let state;
let answer;
const posts = [];
vi.mock('../api.js', () => ({
  api: {
    get: async () => {
      if (state instanceof Error) throw state;
      return state;
    },
    post: async (url) => {
      posts.push(url);
      if (answer instanceof Error || (answer && answer.error)) throw answer;
      return answer;
    },
  },
}));

const { renderHostSetCard, hostSetStatus } = await import('../components/host-set-card.js');

const flush = () => new Promise((r) => setTimeout(r, 0));
const mount = () => /** @type {HTMLElement} */ (document.getElementById('host-set-card'));
const el = (id) => /** @type {any} */ (mount().querySelector(`#${id}`));
const PKGS = [
  { name: 'linux-image-amd64', installed: '6.12.117-1', offered: '6.12.117-1', tested: '6.12.117-1' },
  { name: 'zfs-dkms', installed: '2.4.4-1~bpo13+1', offered: '2.4.4-1~bpo13+1', tested: '2.4.4-1~bpo13+1' },
  {
    name: 'docker.io',
    installed: '26.1.5+dfsg1-9+deb13u1',
    offered: '26.1.5+dfsg1-9+deb13u1+b1',
    tested: '26.1.5+dfsg1-9+deb13u1+b1',
  },
];

beforeEach(() => {
  posts.length = 0;
  state = {
    managed: true,
    packages: PKGS,
    move: ['docker.io'],
    waiting: [],
    running: false,
    restart_needed: false,
    last: null,
  };
  answer = { ...state, move: [], last: { result: 'moved' } };
  document.body.innerHTML = '<div id="host-set-card" hidden></div>';
});

describe('Kernel, ZFS and Docker', () => {
  it('says where things stand', () => {
    expect(hostSetStatus({ running: true })).toContain('Apps keep running');
    expect(hostSetStatus({ last: { result: 'failed', error: 'E: no space' } })).toBe(
      'The last try did not work: E: no space'
    );
    expect(hostSetStatus({ last: { result: 'zfs_missing', error: 'ZFS is not built for 7.3.4.' } })).toBe(
      'ZFS is not built for 7.3.4.'
    );
    expect(hostSetStatus({ restart_needed: true })).toContain('Restart this machine');
    expect(hostSetStatus({ move: ['docker.io'] })).toContain('ready to install');
    expect(hostSetStatus({ move: [], waiting: ['linux-image-amd64'] })).toContain('Debian offers newer versions');
    expect(hostSetStatus({ move: [], waiting: [] })).toBe('As tested with this Kiboto.');
  });

  it('stays hidden where Kiboto is a guest and when it cannot be read', async () => {
    for (const st of [{ managed: false }, new Error('403')]) {
      state = st;
      await renderHostSetCard();
      expect(mount().hidden).toBe(true);
      expect(mount().innerHTML).toBe('');
    }
    document.body.innerHTML = '';
    expect(await renderHostSetCard()).toBe(null);
  });

  it('shows the three, offers the tested versions and installs them', async () => {
    await renderHostSetCard();
    expect(mount().hidden).toBe(false);
    expect(el('hset-docker').textContent.replace(/\s+/g, ' ').trim()).toBe(
      'Docker 26.1.5+dfsg1-9+deb13u1 to 26.1.5+dfsg1-9+deb13u1+b1'
    );
    expect(el('hset-kernel').textContent).not.toContain(' to ');
    el('hset-apply').click();
    await flush();
    expect(posts).toEqual(['/api/system/host-set/apply']);
    expect(el('hset-apply')).toBeNull();
    expect(el('hset-status').textContent).toBe('As tested with this Kiboto.');
  });

  it('checks Debian, says why something did not work, and stays quiet when the person says no', async () => {
    state = { ...state, move: [], packages: [] };
    await renderHostSetCard();
    expect(el('hset-apply')).toBeNull();
    expect(el('hset-kernel').textContent).toContain('-');
    answer = new Error("Debian's package lists could not be read. Is the machine online?");
    el('hset-check').click();
    await flush();
    expect(el('hset-error').textContent).toContain('package lists could not be read');
    expect(el('hset-check').disabled).toBe(false);
    answer = { error: 'cancelled' };
    el('hset-check').click();
    await flush();
    expect(el('hset-check').disabled).toBe(false);
    answer = { ...state, waiting: ['linux-image-amd64'] };
    el('hset-check').click();
    await flush();
    expect(posts.at(-1)).toBe('/api/system/host-set/check');
    expect(el('hset-status').textContent).toContain('Debian offers newer versions');
  });

  it('offers nothing to install while it runs', async () => {
    state = { ...state, running: true };
    await renderHostSetCard();
    expect(el('hset-apply')).toBeNull();
    expect(el('hset-status').textContent).toContain('Apps keep running');
  });
});

describe('a kernel that takes Debian security fixes', () => {
  const follows = ['linux-image-amd64', 'linux-headers-amd64'];

  it('says so on the kernel row and under the title', async () => {
    state = { ...state, move: [], follows_debian: follows, security: { on: true, last: null, kernel_without_zfs: '' } };
    await renderHostSetCard();
    expect(el('hset-help').textContent).toContain('installs its security fixes by itself');
    expect(el('hset-kernel').textContent).toContain("takes Debian's security fixes");
    expect(el('hset-zfs').textContent).not.toContain('security');
  });

  it('names the new kernel that waits for ZFS', () => {
    expect(hostSetStatus({ security: { on: true, kernel_without_zfs: '6.12.120+deb13-amd64' } })).toBe(
      'ZFS is not built for the new kernel 6.12.120+deb13-amd64 yet, so this machine keeps starting the kernel it runs now.'
    );
    expect(hostSetStatus({ running: true, security: { kernel_without_zfs: 'x' } })).toContain('Apps keep running');
  });

  it('says when the automatic fixes are off', async () => {
    state = { ...state, security: { on: false, last: null, kernel_without_zfs: '' } };
    await renderHostSetCard();
    expect(el('hset-help').textContent).toContain('KIBOTO_SECURITY_UPDATES=0');
    expect(el('hset-kernel').textContent).not.toContain('security');
  });
});
