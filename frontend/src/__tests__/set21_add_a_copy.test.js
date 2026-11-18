import { describe, it, expect, vi, beforeEach } from 'vitest';

const get = vi.fn();
const put = vi.fn();
const post = vi.fn();
vi.mock('../api.js', () => ({ api: { get, put, post } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
vi.mock('../components/offsite-backup.js', () => ({ offerRecoveryKit: vi.fn() }));

const pn = await import('../components/protect-nas.js');
const SHARES = [{ name: 'photos', path: '/mnt/pool/photos' }];

const form = (dest, pick) => {
  document.body.innerHTML = pn.guideHtml(dest, SHARES);
  const f = /** @type {HTMLFormElement} */ (document.querySelector('[data-protect-form]'));
  if (pick) /** @type {HTMLInputElement} */ (f.querySelector(`input[value="${pick}"]`)).checked = true;
  return f;
};

describe('one way to add a copy (SET-21 stage 3)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    put.mockResolvedValue({});
    post.mockResolvedValue({});
  });

  it('a paired Kiboto is a place to pick, by its name', () => {
    form({ usb: [], nas: [], cloud: [], kiboto: [{ value: 'abcdef0123456789', label: "Grandma's Kiboto" }] });
    const radio = document.querySelector('input[value="kiboto|abcdef0123456789"]');
    expect(radio?.parentElement?.textContent).toContain("Grandma's Kiboto");
    form({ usb: [], nas: [], cloud: [], kiboto: [] });
    expect(document.body.textContent).toContain('Network → Backup buddy');
  });

  it('a paired Kiboto gives the space, then the schedule from More options, then the first run', async () => {
    const f = form({ kiboto: [{ value: 'abcdef0123456789', label: 'Grandma' }] }, 'kiboto|abcdef0123456789');
    /** @type {HTMLInputElement} */ (f.querySelector('[name="hour"]')).value = '4';
    get.mockResolvedValue({
      repos: [{ id: 'buddy-abcdef01', name: 'Buddy: Grandma', location: 'rest:http://g:8000/u/' }],
    });
    expect(await pn.protect(f)).toBe('buddy-abcdef01');
    expect(post).toHaveBeenCalledWith('/api/fleet/peers/abcdef0123456789/backup', { paths: ['/mnt/pool/photos'] });
    expect(put).toHaveBeenCalledWith(
      '/api/offsite/repos',
      expect.objectContaining({
        id: 'buddy-abcdef01',
        location: 'rest:http://g:8000/u/',
        hour: 4,
        keep: { daily: 7, weekly: 4, monthly: 12 },
      })
    );
    expect(post).toHaveBeenLastCalledWith('/api/offsite/repos/buddy-abcdef01/backup', {});
  });

  it('somewhere else is used when nothing above is picked', async () => {
    const f = form({ usb: [], nas: [], cloud: [] });
    /** @type {HTMLInputElement} */ (f.querySelector('[name="custom"]')).value = 'rclone:b2:home';
    const id = await pn.protect(f);
    expect(put).toHaveBeenCalledWith(
      '/api/offsite/repos',
      expect.objectContaining({ location: 'rclone:b2:home', name: 'Backup: rclone:b2:home', hour: 2 })
    );
    expect(post).toHaveBeenCalledWith(`/api/offsite/repos/${id}/init`, {});
  });

  it('the schedule keeps its defaults for empty fields and stays inside the day', () => {
    const f = new FormData();
    f.set('hour', '30');
    f.set('daily', '');
    expect(pn.scheduleOf(f)).toEqual({ hour: 23, keep: { daily: 7, weekly: 4, monthly: 12 } });
  });
});
