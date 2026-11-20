// Backup: "A second NAS that can take over" (high availability, the owner's decisions of 19 Nov 2026).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '../api.js';
import { showToast } from '../toast.js';
import { renderHaCard, resetHaCardForTesting, haReach, haRole, haCopy } from '../components/management/ha-card.js';

vi.mock('../toast.js', async (orig) => ({ ...(await orig()), showToast: vi.fn() }));

const NONE = { role: '', name: 'Second NAS', code_waiting: false, peer: null };
const PEER = {
  name: 'First NAS',
  address: 'http://192.168.1.10:8082',
  paired_at: 1763600000,
  last_contact: 1763600300,
  reachable: true,
  error: '',
};
const flush = () => new Promise((r) => setTimeout(r, 0));
const card = () => document.getElementById('ha-card');
const press = async (action) => {
  card().querySelector(`[data-ha-act="${action}"]`).click();
  await flush();
  await flush();
};

describe('a second NAS that can take over', () => {
  beforeEach(() => {
    resetHaCardForTesting();
    document.body.innerHTML = '<section class="drawer-card offsite-card"></section><div id="next"></div>';
  });
  afterEach(() => {
    resetHaCardForTesting();
    vi.restoreAllMocks();
    vi.mocked(showToast).mockClear();
    document.body.innerHTML = '';
  });

  it('says how the last contact went', () => {
    expect(haReach({ ...PEER, reachable: null })).toBe('Not checked since this NAS started.');
    expect(haReach(PEER)).toMatch(/^Reached .+\.$/);
    expect(haReach({ ...PEER, reachable: false, error: 'clock' })).toMatch(
      /^Not reached .+: the two boxes do not agree on the time\.$/
    );
    expect(haReach({ ...PEER, reachable: false, error: 'something new' })).toMatch(/: it did not answer\.$/);
    expect(haRole({ role: 'second', peer: PEER })).toBe(
      'This is the second NAS. The first one is First NAS at http://192.168.1.10:8082.'
    );
    expect(haRole({ role: 'first', peer: { ...PEER, name: 'Spare' } })).toMatch(
      /^This is the first NAS\. The second one is Spare at /
    );
  });

  it('offers both parts when the box is not paired, right after the copies outside', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(NONE);
    expect(await renderHaCard()).toBe(true);
    expect(card().previousElementSibling.className).toBe('drawer-card offsite-card');
    expect([...card().querySelectorAll('[data-ha-act]')].map((b) => b.dataset.haAct)).toEqual(['first', 'second']);
    await renderHaCard();
    expect(document.querySelectorAll('#ha-card').length).toBe(1); // drawn again, not twice
  });

  it('the first NAS shows the pairing key once', async () => {
    vi.spyOn(api, 'get')
      .mockResolvedValueOnce(NONE)
      .mockResolvedValueOnce({ ...NONE, role: 'first', peer: PEER });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ code: 'ABCD-EFGH-JKLM-NPQR', valid_seconds: 600 });
    await renderHaCard();
    await press('first');
    expect(post).toHaveBeenCalledWith('/api/ha/code', {});
    expect(card().querySelector('#ha-code').textContent).toBe('ABCD-EFGH-JKLM-NPQR');
    expect(card().textContent).toContain('good for 10 minutes');
    await press('cancel'); // Done: the key leaves the screen, and the card shows who paired meanwhile
    expect(card().querySelector('#ha-code')).toBeNull();
    expect(card().textContent).not.toContain('ABCD-EFGH');
    expect(card().querySelector('#ha-role').textContent).toMatch(/^This is the first NAS/);
  });

  it('the second NAS pairs with the address and the key, and says what went wrong', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(NONE);
    const post = vi
      .spyOn(api, 'post')
      .mockRejectedValueOnce({ error: 'ha_bad_pairing', message: 'The pairing key is not right.' })
      .mockResolvedValueOnce({ ...NONE, role: 'second', peer: PEER });
    await renderHaCard();
    await press('second');
    const form = card().querySelector('#ha-pair-form');
    form.querySelector('[name="address"]').value = ' http://192.168.1.10:8082 ';
    form.querySelector('[name="code"]').value = 'ABCD-EFGH-JKLM-NPQR';
    expect(form.querySelector('[name="mine"]').value).toBe(window.location.origin);
    form.querySelector('[name="mine"]').value = 'http://192.168.1.20:8082';
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    await flush();
    expect(post).toHaveBeenLastCalledWith('/api/ha/pair', {
      address: 'http://192.168.1.10:8082',
      code: 'ABCD-EFGH-JKLM-NPQR',
      my_address: 'http://192.168.1.20:8082',
    });
    expect(card().querySelector('[role="alert"]').textContent).toBe('The pairing key is not right.');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    await flush();
    expect(vi.mocked(showToast).mock.calls[0][0]).toBe('Paired. This is the second NAS now.');
    expect(card().querySelector('#ha-role').textContent).toMatch(
      /^This is the second NAS\. The first one is First NAS/
    );
  });

  it('a paired box can be checked and unpaired', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ ...NONE, role: 'second', peer: { ...PEER, reachable: null } });
    const post = vi
      .spyOn(api, 'post')
      .mockResolvedValue({ ...NONE, role: 'second', peer: { ...PEER, reachable: false, error: 'unreachable' } });
    const del = vi.spyOn(api, 'delete').mockResolvedValue(NONE);
    await renderHaCard();
    expect(card().querySelector('#ha-reach').textContent).toBe('Not checked since this NAS started.');
    await press('check');
    expect(post).toHaveBeenCalledWith('/api/ha/check', {});
    expect(card().querySelector('#ha-reach').textContent).toMatch(/: it did not answer\.$/);
    await press('unpair');
    expect(del).toHaveBeenCalledWith('/api/ha');
    expect(card().querySelector('#ha-role')).toBeNull();
    expect(card().querySelector('[data-ha-act="first"]')).not.toBeNull();
  });

  it('says when the other box was reached, and what went wrong with a step', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ ...NONE, role: 'second', peer: PEER });
    const post = vi
      .spyOn(api, 'post')
      .mockRejectedValueOnce({ error: 'ha_unreachable', message: 'The other NAS did not answer.' })
      .mockRejectedValueOnce({ error: 'cancelled' });
    await renderHaCard();
    expect(card().querySelector('#ha-reach').textContent).toMatch(/^Reached .+\.$/);
    await press('check');
    expect(vi.mocked(showToast).mock.calls[0]).toEqual(["That didn't work: The other NAS did not answer.", 'error']);
    await press('check'); // a confirmation that was cancelled is not an error
    expect(showToast).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledTimes(2);
  });

  it('a pairing that fails without words still says so, and a cancelled one says nothing', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(NONE);
    vi.spyOn(api, 'post').mockRejectedValueOnce({ error: 'cancelled' }).mockRejectedValueOnce({});
    await renderHaCard();
    await press('second');
    const form = card().querySelector('#ha-pair-form');
    const alert = card().querySelector('[role="alert"]');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    await flush();
    expect(alert.hidden).toBe(true);
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    await flush();
    expect(alert.hidden).toBe(false);
    expect(alert.textContent).toBe("That didn't work: ");
  });

  it('says what the second NAS keeps of people and settings, and fetches when asked', async () => {
    const copy = { name: 'First NAS', made: 1763600000, fetched: 1763600100, size: 3 * 1024 * 1024, version: '2.0.5' };
    expect(haCopy({ role: 'second', copy: null })).toBe("No copy of the first NAS's people and settings yet.");
    expect(haCopy({ role: 'second', copy })).toMatch(
      /^People and settings of First NAS: a copy from .+ \(3(\.0)? MB\)\. It is applied only when this NAS takes over\.$/
    );
    expect(haCopy({ role: 'second', copy, fetch_error: 'unreachable' })).toMatch(
      /takes over\. The last fetch did not work\.$/
    );
    expect(haCopy({ role: 'second', copy, fetching: true })).toBe('Fetching people and settings from the first NAS…');
    expect(haCopy({ role: 'first', served: null })).toBe('The second NAS has not fetched people and settings yet.');
    expect(haCopy({ role: 'first', served: 1763600000 })).toMatch(
      /^The second NAS last fetched people and settings .+\.$/
    );
    vi.spyOn(api, 'get').mockResolvedValue({ ...NONE, role: 'second', peer: PEER, copy: null, fetching: false });
    const post = vi
      .spyOn(api, 'post')
      .mockResolvedValue({ ...NONE, role: 'second', peer: PEER, copy: null, fetching: true });
    await renderHaCard();
    expect(card().querySelector('#ha-copy').textContent).toBe("No copy of the first NAS's people and settings yet.");
    await press('fetch');
    expect(post).toHaveBeenCalledWith('/api/ha/fetch', {});
    expect(card().querySelector('[data-ha-act="fetch"]')).toBeNull(); // not twice at once
    expect(card().querySelector('#ha-copy').textContent).toBe('Fetching people and settings from the first NAS…');
    expect(vi.mocked(showToast).mock.calls[0][0]).toBe('Fetching. The card shows the copy when it has arrived.');
  });

  it('the first NAS has no Fetch button', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ ...NONE, role: 'first', peer: PEER, served: null });
    await renderHaCard();
    expect(card().querySelector('[data-ha-act="fetch"]')).toBeNull();
    expect(card().querySelector('#ha-copy').textContent).toBe(
      'The second NAS has not fetched people and settings yet.'
    );
  });

  it('stays away for someone who may not change the system', async () => {
    vi.spyOn(api, 'get').mockRejectedValue({ status: 403 });
    expect(await renderHaCard()).toBe(false);
    expect(card().hidden).toBe(true);
    document.body.innerHTML = '<div></div>';
    expect(await renderHaCard()).toBe(false);
  });
});
