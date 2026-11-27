// Add a drive (Storage): the ways a pool can grow in words, the drives that fit, and the request sent.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const post = vi.fn(async () => ({ started: true }));
const get = vi.fn();
vi.mock('../api.js', () => ({ api: { get: (...a) => get(...a), post: (...a) => post(...a) } }));

const { whyNot, progressText, wayText, bodyHtml, choice, follow, openPoolGrow } =
  await import('../components/pool-grow.js');
const { growButtonHtml } = await import('../components/chassis-visualizer.js');

const GIB8 = 8 * 1024 ** 3;
const PLAN = {
  pool: 'tank',
  ways: [
    { way: 'mirror', to: '/dev/disk/by-id/a-part1', label: '/dev/disk/by-id/a-part1', count: 1, min: GIB8 },
    { way: 'add_mirror', to: '', label: '', count: 2, min: GIB8 },
  ],
  drives: [
    { path: '/dev/vdh', dev: 'vdh', size_bytes: GIB8 / 2 },
    { path: '/dev/vdf', dev: 'vdf', serial: 'KBTESTDISK6', size_bytes: GIB8 },
    { path: '/dev/vdg', dev: 'vdg', serial: 'KBTESTDISK7', size_bytes: GIB8 },
  ],
  progress: { running: false, percent: null },
};

function box(plan) {
  const el = document.createElement('div');
  el.innerHTML = bodyHtml(plan) + '<button id="pg-start" disabled></button>';
  document.body.append(el);
  return el;
}

describe('Add a drive', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    post.mockClear();
  });

  it('says why a pool cannot take a drive, and what runs now', () => {
    expect(whyNot('not_healthy')).toContain('Replace it first');
    expect(whyNot('cannot_grow')).toContain('cannot take another drive');
    expect(whyNot('')).toContain('cannot read');
    expect(progressText({ running: true, percent: 42.7 })).toContain('42% done');
    expect(progressText({ running: true, percent: null })).toContain('Copying onto the new drive.');
    expect(progressText({ running: false })).toBe('');
    expect(progressText(null)).toBe('');
  });

  it('says what each way does', () => {
    expect(wayText(PLAN.ways[0])).toContain('Make a mirror of /dev/disk/by-id/a-part1');
    expect(wayText(PLAN.ways[1])).toContain('mirror of two drives');
    expect(wayText({ way: 'widen', label: 'raidz1-0' })).toContain('cannot be undone');
    expect(wayText({ way: 'add', profile: 'single' })).toContain('kept once');
    expect(wayText({ way: 'add', profile: 'raid1' })).toContain('spread over it');
  });

  it('greys out drives too small, and is ready only with the right number ticked', () => {
    const el = box(PLAN);
    follow(el, PLAN);
    const boxes = /** @type {HTMLInputElement[]} */ ([...el.querySelectorAll('input[name="pg-drive"]')]);
    expect(boxes.map((b) => b.disabled)).toEqual([true, false, false]);
    expect(el.querySelector('#pg-drives-legend')?.textContent).toContain('choose one');
    boxes[1].checked = true;
    follow(el, PLAN);
    expect(choice(el, PLAN)).toMatchObject({ drives: ['/dev/vdf'], ready: true });
    expect(/** @type {HTMLButtonElement} */ (el.querySelector('#pg-start')).disabled).toBe(false);
    /** @type {HTMLInputElement} */ (el.querySelectorAll('input[name="pg-way"]')[1]).checked = true;
    follow(el, PLAN);
    expect(el.querySelector('#pg-drives-legend')?.textContent).toContain('choose two');
    expect(choice(el, PLAN).ready).toBe(false);
    boxes[2].checked = true;
    expect(choice(el, PLAN)).toMatchObject({ drives: ['/dev/vdf', '/dev/vdg'], ready: true });
  });

  it('shows the reason, the progress, or no drives in place of the choices', () => {
    expect(String(bodyHtml({ ways: [], why: 'not_healthy' }))).toContain('Replace it first');
    expect(String(bodyHtml({ ...PLAN, progress: { running: true, percent: 10 } }))).toContain('10% done');
    expect(String(bodyHtml({ ...PLAN, drives: [] }))).toContain('No empty drive is connected');
  });

  it('opens, sends the chosen way and drives, and closes', async () => {
    get.mockResolvedValue(PLAN);
    const done = vi.fn();
    const dlg = await openPoolGrow('tank', 'Tank', done);
    expect(dlg.querySelector('#pg-title')?.textContent).toContain('Add a drive to Tank');
    /** @type {HTMLInputElement} */ (dlg.querySelectorAll('input[name="pg-drive"]')[2]).click();
    /** @type {HTMLButtonElement} */ (dlg.querySelector('#pg-start')).click();
    await vi.waitFor(() => expect(done).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith('/api/storage/pools/tank/grow', {
      way: 'mirror',
      to: '/dev/disk/by-id/a-part1',
      drives: ['/dev/vdg'],
    });
    post.mockRejectedValueOnce(new Error('That drive is not an empty drive.'));
    get.mockResolvedValue(PLAN);
    const again = await openPoolGrow('tank');
    /** @type {HTMLInputElement} */ (again.querySelectorAll('input[name="pg-drive"]')[1]).click();
    /** @type {HTMLButtonElement} */ (again.querySelector('#pg-start')).click();
    await vi.waitFor(() => expect(again.querySelector('#pg-error')?.textContent).toContain('not an empty drive'));
    /** @type {HTMLButtonElement} */ (again.querySelector('[data-pg-close]')).click();
    expect(document.getElementById('pool-grow-dialog')).toBeNull();
  });

  it('a cancelled confirmation leaves the dialog as it was; an unreadable plan says so', async () => {
    get.mockResolvedValue(PLAN);
    post.mockRejectedValueOnce(Object.assign(new Error('cancelled'), { error: 'cancelled' }));
    const dlg = await openPoolGrow('tank');
    /** @type {HTMLInputElement} */ (dlg.querySelectorAll('input[name="pg-drive"]')[1]).click();
    /** @type {HTMLButtonElement} */ (dlg.querySelector('#pg-start')).click();
    await vi.waitFor(() =>
      expect(/** @type {HTMLButtonElement} */ (dlg.querySelector('#pg-start')).disabled).toBe(false)
    );
    expect(dlg.querySelector('#pg-error')?.hasAttribute('hidden')).toBe(true);
    get.mockRejectedValueOnce(new Error('Kiboto is restarting'));
    const broken = await openPoolGrow('tank');
    expect(broken.querySelector('#pg-error')?.textContent).toContain('restarting');
  });

  it('the button shows only for pools that can grow here', () => {
    expect(growButtonHtml({ id: 'tank', name: 'tank', growable: true })).toContain('btn-pool-grow');
    expect(growButtonHtml({ id: 'tank', name: 'tank' })).toBe('');
    expect(growButtonHtml(null)).toBe('');
  });
});
