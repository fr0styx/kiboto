// Security: "Your own scripts" (owner's decision, 19 Nov 2026).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '../api.js';
import { showToast, showDangerConfirm } from '../toast.js';
import {
  renderScriptsCard,
  resetScriptsCardForTesting,
  scheduleSaid,
  lastRunSaid,
  runsNode,
} from '../components/management/scripts-card.js';

vi.mock('../toast.js', async (orig) => ({ ...(await orig()), showToast: vi.fn(), showDangerConfirm: vi.fn() }));

const NIGHT = {
  id: 'a1',
  name: 'Night copy',
  body: 'echo hi',
  schedule: { kind: 'daily', at: '03:30' },
  enabled: true,
  limit_folder: '/mnt/user/Downloads',
  timeout_min: 30,
  next_run: 1795000000,
  running: null,
  last_run: { started: 1794990000, ok: true, exit_code: 0 },
};
const view = (over = {}) => ({
  enabled: true,
  can_limit: true,
  max_scripts: 20,
  max_timeout_min: 720,
  scripts: [NIGHT],
  ...over,
});
const flush = () => new Promise((r) => setTimeout(r, 0));
const card = () => document.getElementById('sec-scripts');
const press = async (selector) => {
  card().querySelector(selector).click();
  await flush();
  await flush();
};

describe('your own scripts', () => {
  beforeEach(() => {
    resetScriptsCardForTesting();
    document.body.innerHTML = '<div id="sec-advisor-card"></div><div id="sec-outside-checks"></div>';
  });
  afterEach(() => {
    resetScriptsCardForTesting();
    vi.restoreAllMocks();
    vi.mocked(showToast).mockClear();
    vi.mocked(showDangerConfirm).mockClear();
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('says a schedule and a last run in words', () => {
    expect(scheduleSaid({ schedule: { kind: 'hourly', minute: 5 } })).toBe('Every hour at xx:05');
    expect(scheduleSaid({ schedule: { kind: 'daily', at: '03:30' } })).toBe('Every day at 03:30');
    expect(scheduleSaid({ schedule: { kind: 'weekly', at: '22:00', days: [0, 2] } })).toBe('Mon, Wed at 22:00');
    expect(scheduleSaid({ schedule: { kind: 'manual' } })).toBe('Runs only when you press Run');
    expect(scheduleSaid({})).toBe('Runs only when you press Run');
    expect(lastRunSaid({})).toBe('Has not run yet');
    expect(lastRunSaid({ running: { started: 1794990000 } })).toMatch(/^Running since /);
    expect(lastRunSaid({ last_run: { started: 1, ok: true } })).toMatch(/finished well$/);
    expect(lastRunSaid({ last_run: { started: 1, exit_code: 3 } })).toMatch(/ended with an error \(code 3\)$/);
    expect(lastRunSaid({ last_run: { started: 1, timed_out: true } })).toMatch(/stopped at its time limit$/);
    expect(lastRunSaid({ last_run: { started: 1, stopped: true } })).toMatch(/stopped by hand$/);
    expect(lastRunSaid({ last_run: { started: 1, limit_failed: true } })).toMatch(/folder limit could not be set up$/);
  });

  it('is hidden from anyone the server refuses, and needs its place on the page', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('403'));
    expect(await renderScriptsCard()).toBe(false);
    expect(card().hidden).toBe(true);
    document.body.innerHTML = '';
    expect(await renderScriptsCard()).toBe(false);
  });

  it('is off until turned on, and says so', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view({ enabled: false, scripts: [] }));
    const put = vi.spyOn(api, 'put').mockResolvedValue(view({ scripts: [] }));
    expect(await renderScriptsCard()).toBe(true);
    await renderScriptsCard(); // drawn again: one card, bound once
    expect(document.querySelectorAll('#sec-scripts').length).toBe(1);
    expect(card().previousElementSibling.id).toBe('sec-outside-checks');
    expect(card().textContent).toContain('Off. No script runs.');
    expect(card().textContent).toContain("A script runs with Kiboto's rights");
    expect(card().querySelector('#scripts-add')).toBe(null); // nothing to add while it is off
    const toggle = card().querySelector('#scripts-toggle');
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    vi.mocked(api.get).mockResolvedValue(view({ scripts: [] }));
    await press('#scripts-toggle');
    expect(put).toHaveBeenCalledWith('/api/scripts/enabled', { enabled: true });
    expect(showToast).toHaveBeenCalledWith('Scripts are on.', 'success');
    expect(card().querySelector('#scripts-toggle').getAttribute('aria-pressed')).toBe('true');
    expect(card().textContent).toContain('No scripts yet.');
    expect(card().textContent).toContain('On: 0 scripts');
    vi.mocked(api.get).mockResolvedValue(view({ enabled: false, scripts: [] }));
    put.mockResolvedValue(view({ enabled: false, scripts: [] }));
    await press('#scripts-toggle');
    expect(put).toHaveBeenLastCalledWith('/api/scripts/enabled', { enabled: false });
    expect(showToast).toHaveBeenLastCalledWith('Scripts are off. Nothing runs.', 'success');
  });

  it('lists a script with what it does, and runs it', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view());
    const post = vi.spyOn(api, 'post').mockResolvedValue({ status: 'started' });
    await renderScriptsCard();
    const row = card().querySelector('[data-script-row="a1"]');
    expect(row.textContent).toContain('Night copy');
    expect(row.textContent).toContain('Every day at 03:30');
    expect(row.textContent).toContain('May change files only in /mnt/user/Downloads');
    expect(row.textContent).toContain('finished well');
    expect(row.textContent).toContain('Next: ');
    expect(card().textContent).toContain('On: 1 script');
    vi.mocked(api.get).mockResolvedValue(view({ scripts: [{ ...NIGHT, running: { started: 1795000100 } }] }));
    await press('[data-script-act="run"]');
    expect(post).toHaveBeenCalledWith('/api/scripts/a1/run', {});
    expect(showToast).toHaveBeenCalledWith('Started.', 'success');
    expect(card().querySelector('[data-script-act="run"]')).toBe(null); // while it runs the button stops it
    expect(card().textContent).toContain('Running since');
    vi.mocked(api.get).mockResolvedValue(view());
    await press('[data-script-act="stop"]');
    expect(post).toHaveBeenLastCalledWith('/api/scripts/a1/stop', {});
    expect(card().querySelector('[data-script-act="run"]')).not.toBe(null);
  });

  it('says why something did not work', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view());
    vi.spyOn(api, 'post').mockRejectedValue(new Error('This script is already running.'));
    await renderScriptsCard();
    await press('[data-script-act="run"]');
    expect(showToast).toHaveBeenCalledWith("That didn't work: This script is already running.", 'error');
  });

  it('shows a paused script and one with full rights as what they are', async () => {
    const paused = {
      ...NIGHT,
      id: 'b2',
      name: 'Paused',
      enabled: false,
      limit_folder: '',
      last_run: null,
      next_run: null,
    };
    vi.spyOn(api, 'get').mockResolvedValue(view({ scripts: [paused] }));
    await renderScriptsCard();
    const text = card().querySelector('[data-script-row="b2"]').textContent;
    expect(text).toContain('Paused: it does not run on its schedule');
    expect(text).toContain('Full rights');
    expect(text).toContain('Has not run yet');
    expect(text).not.toContain('Next: ');
  });

  it('adds a script from the form, with the schedule and the folder limit chosen', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view({ scripts: [] }));
    const post = vi.spyOn(api, 'post').mockResolvedValue(view());
    await renderScriptsCard();
    await press('#scripts-add');
    const form = card().querySelector('form[data-script-form="new"]');
    const q = (name) => form.querySelector(`[name="${name}"]`);
    const shown = (name) => !q(name).closest('.ddns-field').hidden;
    expect(shown('at')).toBe(true); // a new script starts as "every day"
    expect(shown('minute')).toBe(false);
    expect(shown('folder')).toBe(false);
    q('kind').value = 'hourly';
    q('kind').dispatchEvent(new Event('change'));
    expect(shown('minute')).toBe(true);
    expect(shown('at')).toBe(false);
    q('kind').value = 'weekly';
    q('kind').dispatchEvent(new Event('change'));
    expect(shown('at')).toBe(true);
    expect(form.querySelectorAll('[name="day"]').length).toBe(7);
    form.querySelectorAll('[name="day"]')[0].checked = true;
    form.querySelectorAll('[name="day"]')[6].checked = true;
    q('scope').value = 'folder';
    q('scope').dispatchEvent(new Event('change'));
    expect(shown('folder')).toBe(true);
    q('name').value = 'Weekly tidy';
    q('body').value = 'find . -name "*.tmp" -delete';
    q('at').value = '04:15';
    q('folder').value = ' /mnt/user/Downloads ';
    q('timeout').value = '45';
    q('enabled').checked = false;
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(post).toHaveBeenCalledWith('/api/scripts', {
      name: 'Weekly tidy',
      body: 'find . -name "*.tmp" -delete',
      schedule: { kind: 'weekly', at: '04:15', days: [0, 6] },
      enabled: false,
      limit_folder: '/mnt/user/Downloads',
      timeout_min: 45,
    });
    expect(showToast).toHaveBeenCalledWith('Saved.', 'success');
    expect(card().querySelector('form')).toBe(null);
    expect(card().querySelector('[data-script-row="a1"]')).not.toBe(null);
  });

  it('keeps the form and says what is wrong when the server refuses it, and Cancel closes it', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view({ scripts: [], can_limit: false }));
    vi.spyOn(api, 'post').mockRejectedValue(new Error('The script is empty.'));
    await renderScriptsCard();
    await press('#scripts-add');
    let form = card().querySelector('form');
    expect(form.querySelector('[name="scope"] option[value="folder"]').disabled).toBe(true);
    expect(form.textContent).toContain('This system cannot limit a script to a folder.');
    form.querySelector('[name="kind"]').value = 'hourly';
    form.querySelector('[name="kind"]').dispatchEvent(new Event('change'));
    form.querySelector('[name="minute"]').value = '15';
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    form = card().querySelector('form');
    expect(form.querySelector('[role="alert"]').textContent).toBe('The script is empty.');
    expect(form.querySelector('[role="alert"]').hidden).toBe(false);
    expect(vi.mocked(api.post).mock.calls[0][1].schedule).toEqual({ kind: 'hourly', minute: 15 });
    expect(vi.mocked(api.post).mock.calls[0][1].limit_folder).toBe('');
    form.querySelector('button[type="button"]').click();
    expect(card().querySelector('form')).toBe(null);
  });

  it('changes a script in place', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view());
    const put = vi.spyOn(api, 'put').mockResolvedValue(view({ scripts: [{ ...NIGHT, name: 'Renamed' }] }));
    await renderScriptsCard();
    await press('[data-script-act="edit"]');
    const form = card().querySelector('form[data-script-form="a1"]');
    expect(form.querySelector('[name="name"]').value).toBe('Night copy');
    expect(form.querySelector('[name="scope"]').value).toBe('folder');
    expect(form.querySelector('[name="folder"]').value).toBe('/mnt/user/Downloads');
    form.querySelector('[name="name"]').value = 'Renamed';
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    await flush();
    expect(put.mock.calls[0][0]).toBe('/api/scripts/a1');
    expect(put.mock.calls[0][1].name).toBe('Renamed');
    expect(card().textContent).toContain('Renamed');
    await press('[data-script-act="edit"]');
    await press('[data-script-act="edit"]'); // pressed again: the form closes
    expect(card().querySelector('form')).toBe(null);
  });

  it('shows the last runs with what they printed', async () => {
    const runs = {
      running: null,
      runs: [
        {
          started: 1794990000,
          ok: true,
          exit_code: 0,
          how: 'schedule',
          who: '',
          output: 'copied 3 files\n',
          output_bytes: 15,
        },
        { started: 1794900000, ok: false, exit_code: 2, how: 'by_hand', who: 'ana', output: '', output_bytes: 0 },
        { started: 1794800000, ok: true, exit_code: 0, how: 'by_hand', who: '', output: 'tail', output_bytes: 90000 },
      ],
    };
    const node = runsNode(NIGHT, runs);
    expect(node.textContent).toContain('Last runs of “Night copy”');
    expect(node.querySelectorAll('pre').length).toBe(3);
    expect(node.querySelectorAll('pre')[0].textContent).toBe('copied 3 files\n');
    expect(node.querySelectorAll('pre')[1].textContent).toBe('It printed nothing.');
    expect(node.textContent).toContain('on its schedule');
    expect(node.textContent).toContain('started by ana');
    expect(node.textContent).toContain('started by ?');
    expect(node.textContent).toContain('Only the end of what it printed is kept.');
    expect(runsNode(NIGHT, null).textContent).toContain('No runs on record.');

    vi.spyOn(api, 'get').mockImplementation(async (path) => (path.endsWith('/runs') ? runs : view()));
    await renderScriptsCard();
    await press('[data-script-act="runs"]');
    expect(api.get).toHaveBeenCalledWith('/api/scripts/a1/runs');
    expect(card().querySelector('[data-script-runs="a1"] pre').textContent).toBe('copied 3 files\n');
    await press('[data-script-act="runs"]'); // pressed again: closed
    expect(card().querySelector('[data-script-runs="a1"]')).toBe(null);
  });

  it('asks before deleting, then deletes', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(view());
    const del = vi.spyOn(api, 'delete').mockResolvedValue(view({ scripts: [] }));
    await renderScriptsCard();
    await press('[data-script-act="edit"]');
    await press('[data-script-act="delete"]');
    expect(del).not.toHaveBeenCalled();
    const [title, msg, yes] = vi.mocked(showDangerConfirm).mock.calls[0];
    expect(title).toBe('Delete the script');
    expect(msg).toBe('Delete the script “Night copy”? The record of its runs goes too.');
    vi.mocked(api.get).mockResolvedValue(view({ scripts: [] }));
    await yes();
    await flush();
    expect(del).toHaveBeenCalledWith('/api/scripts/a1');
    expect(showToast).toHaveBeenCalledWith('Deleted.', 'success');
    expect(card().querySelector('[data-script-row="a1"]')).toBe(null);
  });

  it('looks again only while a script is running, and stops when the card is gone', async () => {
    vi.useFakeTimers();
    const get = vi
      .spyOn(api, 'get')
      .mockResolvedValue(view({ scripts: [{ ...NIGHT, running: { started: 1795000100 } }] }));
    await renderScriptsCard();
    expect(get).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3100);
    expect(get).toHaveBeenCalledTimes(2);
    get.mockResolvedValue(view()); // it finished
    await vi.advanceTimersByTimeAsync(3100);
    expect(get).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(9000);
    expect(get).toHaveBeenCalledTimes(3); // nothing runs: nothing is asked
    get.mockResolvedValue(view({ scripts: [{ ...NIGHT, running: { started: 1795000100 } }] }));
    await renderScriptsCard();
    card().remove();
    await vi.advanceTimersByTimeAsync(7000);
    expect(get).toHaveBeenCalledTimes(4); // the card left the page: the looking stops
  });

  it('does not redraw under someone who is typing', async () => {
    vi.useFakeTimers();
    const get = vi
      .spyOn(api, 'get')
      .mockResolvedValue(view({ scripts: [{ ...NIGHT, running: { started: 1795000100 } }] }));
    await renderScriptsCard();
    card().querySelector('#scripts-add').click();
    const field = card().querySelector('form [name="name"]');
    field.value = 'half typed';
    await vi.advanceTimersByTimeAsync(3100);
    expect(get).toHaveBeenCalledTimes(2);
    expect(card().querySelector('form [name="name"]').value).toBe('half typed');
    // found in a real browser: a save must redraw even though the form (its Save button) has the focus
    card().querySelector('form button[type="submit"]').focus();
    vi.spyOn(api, 'post').mockResolvedValue(view());
    card().querySelector('form [name="body"]').value = 'echo hi';
    card()
      .querySelector('form')
      .dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.advanceTimersByTimeAsync(10);
    expect(card().querySelector('form')).toBe(null);
    expect(card().querySelector('[data-script-row="a1"]')).not.toBe(null);
  });
});
