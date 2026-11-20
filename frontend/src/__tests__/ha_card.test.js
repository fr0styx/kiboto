// Backup: "A second NAS that can take over" (high availability, the owner's decisions of 19 Nov 2026).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '../api.js';
import { showToast } from '../toast.js';
import {
  renderHaCard,
  resetHaCardForTesting,
  haReach,
  haRole,
  haCopy,
  haFolderLine,
  haAppLine,
  haTiming,
} from '../components/management/ha-card.js';

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

  it('says how the last fetch of a folder went', () => {
    const last = {
      at: 1763600000,
      fetched: 3,
      bytes: 5 * 1024 ** 3,
      same: 120,
      kept_yours: 0,
      removed: 0,
      errors: [],
      why: '',
    };
    expect(haFolderLine('Films', null)).toBe('Films: not fetched yet.');
    expect(haFolderLine('Films', last)).toMatch(
      /^Films, fetched .+: 3 files new or changed \(5(\.0)? GB\), 120 unchanged\.$/
    );
    expect(haFolderLine('Films', { ...last, fetched: 1, removed: 2, kept_yours: 1, errors: [{}] })).toMatch(
      /1 file new or changed .+ 2 files are gone on the first NAS and were put away here\. 1 file of this NAS's own was left alone\. 1 file could not be fetched\.$/
    );
    expect(haFolderLine('Films', { ...last, why: 'full' })).toMatch(/It stopped because this NAS is full\.$/);
    expect(haFolderLine('Films', { at: 1763600000, why: 'make_folder', fetched: 0, same: 0 })).toMatch(
      /^Films: not fetched .+: make a shared folder of that name on this NAS first\.$/
    );
    expect(haFolderLine('Films', { at: 1763600000, why: 'something new', fetched: 0, same: 0 })).toMatch(
      /: it did not work\.$/
    );
  });

  it('the second NAS ticks the folders to keep, and saves the choice', async () => {
    const paired = {
      ...NONE,
      role: 'second',
      peer: PEER,
      copy: null,
      folders: ['Films'],
      folders_last: {},
      keep_removed_days: 30,
    };
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url === '/api/ha/folders' ? { available: ['Films', 'Music', 'Photos'], error: '', folders: ['Films'] } : paired
    );
    const put = vi.spyOn(api, 'put').mockResolvedValue({ ...paired, folders: ['Films', 'Photos'], fetching: true });
    await renderHaCard();
    const boxes = [...card().querySelectorAll('input[data-ha-folder]')];
    expect(boxes.map((b) => [b.dataset.haFolder, b.checked])).toEqual([
      ['Films', true],
      ['Music', false],
      ['Photos', false],
    ]);
    expect(card().querySelector('#ha-folders').textContent).toContain('kept here for 30 days');
    expect(card().querySelector('#ha-folders').textContent).toContain('Films: not fetched yet.');
    boxes[2].checked = true;
    await press('folders');
    expect(put).toHaveBeenCalledWith('/api/ha/folders', { names: ['Films', 'Photos'] });
    expect(vi.mocked(showToast).mock.calls[0][0]).toBe('Saved. The folders are fetched now, and every night.');
    expect([...card().querySelectorAll('input[data-ha-folder]')].filter((b) => b.checked).length).toBe(2);
  });

  it('keeps the chosen folders on screen when the first NAS cannot be asked', async () => {
    const paired = {
      ...NONE,
      role: 'second',
      peer: PEER,
      copy: null,
      folders: ['Films'],
      folders_last: {},
      keep_removed_days: 30,
    };
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/api/ha/folders') throw { status: 409 };
      return paired;
    });
    await renderHaCard();
    expect(card().querySelector('#ha-folders-unasked')).not.toBeNull();
    expect([...card().querySelectorAll('input[data-ha-folder]')].map((b) => b.dataset.haFolder)).toEqual(['Films']);
  });

  it('the first NAS has no Fetch button', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ ...NONE, role: 'first', peer: PEER, served: null });
    await renderHaCard();
    expect(card().querySelector('[data-ha-act="fetch"]')).toBeNull();
    expect(card().querySelector('#ha-copy').textContent).toBe(
      'The second NAS has not fetched people and settings yet.'
    );
  });

  it('the second NAS takes over by a button, and is asked again when the first one still answers', async () => {
    const copy = { name: 'First NAS', made: 1763600000, fetched: 1763600100, size: 1024, version: '2.0.5' };
    const second = { ...NONE, role: 'second', peer: PEER, copy, fetching: false };
    vi.spyOn(api, 'get').mockResolvedValue(second);
    const post = vi.spyOn(api, 'post').mockRejectedValueOnce({ error: 'ha_first_answers', message: 'It answers.' });
    await renderHaCard();
    expect(card().querySelector('#ha-takeover').textContent).toContain('It keeps its own network address');
    expect(card().querySelector('[data-ha-act="takeover_anyway"]')).toBeNull();
    await press('takeover');
    expect(post).toHaveBeenCalledWith('/api/ha/takeover', { even_if_answering: false, bring: [] });
    expect(showToast).not.toHaveBeenCalled(); // a question, not a failure
    expect(card().querySelector('#ha-answers').textContent).toMatch(/^The first NAS still answers/);
    const took = { at: 1763700000, from: 'First NAS', name: 'familynas', people: 4 };
    post.mockResolvedValueOnce({ ...NONE, role: 'took_over', peer: PEER, took_over: took, restarting: true });
    await press('takeover_anyway');
    expect(post).toHaveBeenLastCalledWith('/api/ha/takeover', { even_if_answering: true, bring: [] });
    expect(vi.mocked(showToast).mock.calls.at(-1)[0]).toMatch(/^Taking over\. This NAS restarts now/);
    expect(card().querySelector('#ha-role').textContent).toMatch(
      /^This NAS took over from First NAS on .+\. It answers to familynas\.local\.$/
    );
    expect(card().querySelector('#ha-takeover')).toBeNull();
    expect(card().querySelector('#ha-copy')).toBeNull();
    expect(card().querySelector('[data-ha-act="fetch"]')).toBeNull();
  });

  it('taking over waits for the copy, and says when Kiboto has to be restarted by hand', async () => {
    const second = { ...NONE, role: 'second', peer: PEER, copy: null, fetching: false };
    const get = vi.spyOn(api, 'get').mockResolvedValue(second);
    await renderHaCard();
    expect(card().querySelector('#ha-takeover').textContent).toContain('Fetch it first.');
    expect(card().querySelector('[data-ha-act="takeover"]')).toBeNull();
    resetHaCardForTesting();
    const copy = { name: 'First NAS', made: 1763600000, fetched: 1763600100, size: 1024, version: '2.0.5' };
    get.mockResolvedValue({ ...second, copy });
    vi.spyOn(api, 'post').mockResolvedValue({
      ...NONE,
      role: 'took_over',
      peer: { ...PEER, name: '' },
      took_over: { at: 1763700000, from: '', name: '', people: 1 },
      restarting: false,
    });
    await renderHaCard();
    await press('takeover');
    expect(vi.mocked(showToast).mock.calls.at(-1)[0]).toMatch(/^Taking over\. Restart Kiboto to finish/);
    expect(card().querySelector('#ha-role').textContent).toMatch(/^This NAS took over from \? on .+\.$/);
    expect(haRole({ role: 'took_over', peer: PEER })).toMatch(/^This NAS took over from First NAS on /);
  });

  it('a first NAS whose second one took over says so, and takes its name back', async () => {
    const held = { ...NONE, role: 'first', peer: PEER, served: 1763600000, stood_down: { at: 1763700000 } };
    vi.spyOn(api, 'get').mockResolvedValue(held);
    const post = vi
      .spyOn(api, 'post')
      .mockRejectedValueOnce({ error: 'ha_second_unreachable', message: 'It did not answer.' });
    await renderHaCard();
    expect(card().querySelector('#ha-held').textContent).toMatch(
      /^The second NAS took over \(.+\)\. This NAS does not/
    );
    expect(card().querySelector('#ha-takeover')).toBeNull(); // only a second NAS takes over
    await press('takeback');
    expect(post).toHaveBeenCalledWith('/api/ha/take-back', { even_if_unreachable: false });
    expect(card().querySelector('#ha-unreached').textContent).toMatch(/^The second NAS did not answer/);
    post.mockResolvedValueOnce({ ...held, stood_down: null });
    await press('takeback_anyway');
    expect(post).toHaveBeenLastCalledWith('/api/ha/take-back', { even_if_unreachable: true });
    expect(vi.mocked(showToast).mock.calls.at(-1)[0]).toBe('This NAS answers to its name again.');
    expect(card().querySelector('#ha-held')).toBeNull();
  });

  it('a first NAS that holds nothing back has no such part, and another failure is said as one', async () => {
    const first = { ...NONE, role: 'first', peer: PEER, served: null, stood_down: null };
    vi.spyOn(api, 'get').mockResolvedValue({ ...first, stood_down: { at: 0 } });
    vi.spyOn(api, 'post').mockRejectedValue({
      error: 'ha_not_held',
      message: 'This NAS is not holding its name back.',
    });
    await renderHaCard();
    await press('takeback');
    expect(vi.mocked(showToast).mock.calls.at(-1)[0]).toBe("That didn't work: This NAS is not holding its name back.");
    expect(card().querySelector('#ha-unreached')).toBeNull();
    resetHaCardForTesting();
    vi.mocked(api.get).mockResolvedValue(first);
    await renderHaCard();
    expect(card().querySelector('#ha-held')).toBeNull();
  });

  it('the backups come along only when the box is ticked, and the card says how many came', async () => {
    const copy = {
      name: 'First NAS',
      made: 1763600000,
      fetched: 1763600100,
      size: 1024,
      holds: { backup_jobs: 2, offsite: 1 },
    };
    vi.spyOn(api, 'get').mockResolvedValue({ ...NONE, role: 'second', peer: PEER, copy, fetching: false });
    const took = {
      at: 1763700000,
      from: 'First NAS',
      name: '',
      people: 3,
      brought: { jobs: 2, jobs_left: 1, offsite: 0, offsite_left: 0 },
    };
    const post = vi
      .spyOn(api, 'post')
      .mockResolvedValue({ ...NONE, role: 'took_over', peer: PEER, took_over: took, restarting: true });
    await renderHaCard();
    const tick = card().querySelector('#ha-bring-backups');
    expect(tick.checked).toBe(false); // a choice, off until ticked
    expect(card().querySelector('#ha-bring-note').textContent).toMatch(
      /stays behind\. The copy holds 2 copy jobs and 1 off-site backup\.$/
    );
    tick.checked = true;
    tick.dispatchEvent(new Event('change'));
    tick.checked = false;
    tick.dispatchEvent(new Event('change'));
    tick.checked = true;
    tick.dispatchEvent(new Event('change'));
    await press('takeover');
    expect(post).toHaveBeenCalledWith('/api/ha/takeover', { even_if_answering: false, bring: ['backups'] });
    expect(card().querySelector('#ha-role').textContent).toMatch(
      /^This NAS took over from First NAS on .+\. 2 backups came along, switched off; 1 stayed behind\.$/
    );
    expect(haRole({ role: 'took_over', peer: PEER, took_over: { ...took, brought: {} } })).not.toContain('came along');
    resetHaCardForTesting();
    vi.mocked(api.get).mockResolvedValue({ ...NONE, role: 'second', peer: PEER, copy: { ...copy, holds: undefined } });
    await renderHaCard();
    expect(card().querySelector('#ha-bring-backups').checked).toBe(false); // the tick does not outlive the card
    expect(card().querySelector('#ha-bring-note').textContent).toMatch(/stays behind\.$/); // an older copy: no count
  });

  it('says what is true of each app of the first NAS', () => {
    expect(haAppLine({ name: 'a', state: '', why: null })).toBe('Can be added: its folders are kept here.');
    expect(haAppLine({ name: 'a', state: 'adding' })).toBe('Being added…');
    expect(haAppLine({ name: 'a', state: 'added' })).toBe('Added. It is under Apps.');
    expect(haAppLine({ name: 'a', state: 'here' })).toBe('On this NAS already.');
    expect(haAppLine({ name: 'a', state: 'failed', error: 'the image was not found' })).toBe(
      'Not added: the image was not found'
    );
    expect(haAppLine({ name: 'a', state: 'failed' })).toBe('Not added: ');
    expect(haAppLine({ name: 'a', state: 'needs_review' })).toMatch(
      /^Not added from here: it asks for host-level access/
    );
    expect(haAppLine({ name: 'a', state: '', why: { why: 'folder_not_kept', folder: 'appdata' } })).toBe(
      'Not possible: it keeps files in “appdata”, which is not kept on this NAS.'
    );
    expect(haAppLine({ name: 'a', state: '', why: { why: 'folder_missing', path: '/srv/x' } })).toBe(
      'Not possible: it uses /srv/x, which this NAS does not have.'
    );
    expect(haAppLine({ name: 'a', state: '', why: { why: 'folder_not_kept' } })).toContain('“”');
    expect(haAppLine({ name: 'a', state: '', why: { why: 'something new' } })).toContain('it uses ,');
  });

  it('after a takeover the apps of the first NAS are listed, and one is added when asked', async () => {
    const took = { ...NONE, role: 'took_over', peer: PEER, took_over: { at: 1763700000, from: 'First NAS', name: '' } };
    const apps = [
      { name: 'jellyfin', state: '', why: null },
      { name: 'taxes', state: '', why: { why: 'folder_not_kept', folder: 'taxes' } },
      { name: 'grafana', state: 'here', why: null },
    ];
    const get = vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/ha/apps' ? { apps } : took));
    const adding = apps.map((a) => (a.name === 'jellyfin' ? { ...a, state: 'adding' } : a));
    const post = vi.spyOn(api, 'post').mockResolvedValue({ apps: adding });
    haTiming.poll = 0;
    await renderHaCard();
    const rows = () => [...card().querySelectorAll('#ha-apps .ha-app')].map((r) => r.textContent);
    expect(rows()).toEqual([
      'jellyfinCan be added: its folders are kept here.Add here',
      'taxesNot possible: it keeps files in “taxes”, which is not kept on this NAS.',
      'grafanaOn this NAS already.',
    ]);
    const add = card().querySelector('[data-ha-act="app_add"]');
    expect(add.getAttribute('aria-label')).toBe('Add here: jellyfin');
    // the list is read again while the app is being added, until it is
    get.mockImplementation(async (url) =>
      url === '/api/ha/apps' ? { apps: apps.map((a) => (a.name === 'jellyfin' ? { ...a, state: 'added' } : a)) } : took
    );
    add.click();
    await flush();
    expect(post).toHaveBeenCalledWith('/api/ha/apps/jellyfin/add', {});
    await flush();
    await flush();
    await flush();
    expect(rows()[0]).toBe('jellyfinAdded. It is under Apps.');
    expect(card().querySelector('[data-ha-act="app_add"]')).toBeNull();
    haTiming.poll = 4000;
  });

  it('an app that is still being added is asked about again, and a list that cannot be read is empty', async () => {
    const took = { ...NONE, role: 'took_over', peer: PEER, took_over: { at: 1763700000, from: 'First NAS', name: '' } };
    let asked = 0;
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url !== '/api/ha/apps') return took;
      asked += 1;
      return { apps: [{ name: 'jellyfin', state: asked < 3 ? 'adding' : 'failed', error: 'no room', why: null }] };
    });
    haTiming.poll = 0;
    await renderHaCard();
    for (let i = 0; i < 6; i += 1) await flush();
    expect(asked).toBe(3);
    expect(card().querySelector('#ha-apps .ha-app').textContent).toBe('jellyfinNot added: no roomAdd here'); // can be tried again
    haTiming.poll = 4000;
    resetHaCardForTesting();
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (url === '/api/ha/apps') throw new Error('offline');
      return took;
    });
    await renderHaCard();
    expect(card().querySelector('#ha-apps-none').textContent).toBe('The first NAS told of no apps.');
    resetHaCardForTesting();
    vi.mocked(api.get).mockImplementation(async (url) => (url === '/api/ha/apps' ? {} : took));
    await renderHaCard();
    expect(card().querySelector('#ha-apps-none')).not.toBeNull();
  });

  it('the second NAS says how many apps it was told about, before a takeover', async () => {
    const copy = { name: 'First NAS', made: 1763600000, fetched: 1763600100, size: 1024 };
    vi.spyOn(api, 'get').mockResolvedValue({ ...NONE, role: 'second', peer: PEER, copy, apps_known: 2 });
    await renderHaCard();
    expect(card().querySelector('#ha-apps-known').textContent).toMatch(
      /^The first NAS also told this one how its 2 apps are set up\./
    );
    expect(card().querySelector('#ha-apps')).toBeNull(); // the list comes after the takeover
    resetHaCardForTesting();
    vi.mocked(api.get).mockResolvedValue({ ...NONE, role: 'second', peer: PEER, copy, apps_known: 0 });
    await renderHaCard();
    expect(card().querySelector('#ha-apps-known')).toBeNull();
  });

  it('a part that is not drawn leaves nothing behind, in every state of the card', async () => {
    const copy = { name: 'First NAS', made: 1763600000, fetched: 1763600100, size: 1024 };
    const states = [
      { ...NONE, role: 'first', peer: PEER, served: null },
      { ...NONE, role: 'first', peer: PEER, served: 1763600000, stood_down: { at: 1763700000 } },
      { ...NONE, role: 'second', peer: PEER, copy: null },
      { ...NONE, role: 'second', peer: PEER, copy, fetching: true },
      { ...NONE, role: 'took_over', peer: PEER, took_over: { at: 1763700000, from: 'First NAS', name: '' } },
    ];
    for (const state of states) {
      resetHaCardForTesting();
      vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/ha/apps' ? { apps: [] } : state));
      await renderHaCard();
      expect(card().textContent).not.toMatch(/null|undefined/);
      expect([...card().childNodes].every((n) => n.nodeType === 1)).toBe(true); // elements only, no stray text
    }
  });

  it('stays away for someone who may not change the system', async () => {
    vi.spyOn(api, 'get').mockRejectedValue({ status: 403 });
    expect(await renderHaCard()).toBe(false);
    expect(card().hidden).toBe(true);
    document.body.innerHTML = '<div></div>';
    expect(await renderHaCard()).toBe(false);
  });
});
