// Re-audit R11: coloured labels on files and folders.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '../api.js';
import { showToast } from '../toast.js';
import { setLanguage } from '../i18n.js';
import {
  COLOURS,
  colourWord,
  labelName,
  labelOf,
  labelledPaths,
  labelsInUse,
  loadLabels,
  setLabel,
  nameLabel,
  markLabel,
  openLabelPicker,
  openLabelList,
  resetLabelsForTesting,
} from '../components/fm-labels.js';

vi.mock('../toast.js', async (orig) => ({ ...(await orig()), showToast: vi.fn() }));

const VIEW = {
  colours: COLOURS,
  names: { red: 'Taxes' },
  items: { '/mnt/user/docs/tax.pdf': 'red', '/mnt/user/docs': 'blue', '/mnt/user/a.txt': 'red' },
};

describe('file labels', () => {
  beforeEach(() => {
    resetLabelsForTesting();
    vi.mocked(showToast).mockClear();
  });
  afterEach(async () => {
    vi.restoreAllMocks();
    await setLanguage('en');
    document.body.innerHTML = '';
  });

  it('knows nothing before it is loaded, then answers by path', async () => {
    expect(labelOf('/mnt/user/docs')).toBe('');
    expect(labelsInUse()).toEqual([]);
    const get = vi.spyOn(api, 'get').mockResolvedValue(VIEW);
    await Promise.all([loadLabels(), loadLabels()]); // asked once
    await loadLabels();
    expect(get).toHaveBeenCalledTimes(1);
    expect(labelOf('/mnt/user/docs/')).toBe('blue');
    expect(labelOf('/mnt/user/docs/tax.pdf')).toBe('red');
    expect(labelName('red')).toBe('Taxes');
    expect(labelName('blue')).toBe('Blue');
    expect(colourWord('pink')).toBe('');
    expect(labelledPaths('red')).toEqual(['/mnt/user/a.txt', '/mnt/user/docs/tax.pdf']);
    expect(labelsInUse()).toEqual([
      { colour: 'red', count: 2 },
      { colour: 'blue', count: 1 },
    ]);
    await loadLabels(true);
    expect(get).toHaveBeenCalledTimes(2);
  });

  it('a list that cannot be read leaves no labels, and the colours speak the reader language', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('offline'));
    await loadLabels();
    expect(labelOf('/x')).toBe('');
    await setLanguage('de');
    expect(colourWord('green')).toBe('Grün');
  });

  it('marks a row with the colour and says the name to a screen reader', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(VIEW);
    await loadLabels();
    const row = document.createElement('div');
    expect(markLabel(row, '/mnt/user/docs/tax.pdf')).toBe('red');
    expect(row.dataset.label).toBe('red');
    expect(row.getAttribute('aria-description')).toBe('Label: Taxes');
    expect(markLabel(row, '/mnt/user/other')).toBe('');
    expect(row.dataset.label).toBeUndefined();
    expect(row.hasAttribute('aria-description')).toBe(false);
    expect(markLabel(document.createElement('div'), '/none')).toBe('');
  });

  it('saves a label and a name, and says so when it fails', async () => {
    const put = vi.spyOn(api, 'put').mockResolvedValue({ names: {}, items: { '/a': 'green' } });
    expect(await setLabel('/a/', 'green')).toBe(true);
    expect(put).toHaveBeenCalledWith('/api/fs/labels', { path: '/a', colour: 'green' });
    expect(labelOf('/a')).toBe('green');
    put.mockResolvedValueOnce({ names: { green: 'Garden' }, items: { '/a': 'green' } });
    expect(await nameLabel('green', 'Garden')).toBe(true);
    expect(labelName('green')).toBe('Garden');
    put.mockRejectedValue(new Error('no right'));
    expect(await setLabel('/a', null)).toBe(false);
    expect(await nameLabel('green', 'x')).toBe(false);
    expect(showToast).toHaveBeenCalledWith("The label couldn't be changed: no right", 'error');
  });

  it('the picker: choose a colour, name it, save; or take the label off', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(VIEW);
    await loadLabels();
    const put = vi
      .spyOn(api, 'put')
      .mockImplementation(async (url, body) =>
        url.endsWith('/names')
          ? { names: { red: 'Taxes', green: body.name }, items: VIEW.items }
          : { names: { red: 'Taxes' }, items: { ...VIEW.items, [body.path]: body.colour } }
      );
    const host = openLabelPicker({ path: '/mnt/user/new.txt', name: 'new.txt' });
    expect(host.querySelector('.smart-modal-title').textContent).toBe('Label for new.txt');
    expect(host.querySelectorAll('.fm-label-choice').length).toBe(6);
    expect(host.querySelector('.fm-label-name').hidden).toBe(true);
    const none = [...host.querySelectorAll('button')].find((b) => b.textContent === 'No label');
    expect(none.hidden).toBe(true); // nothing to take off yet
    const green = host.querySelector('[data-colour="green"]');
    green.click();
    expect(green.getAttribute('aria-pressed')).toBe('true');
    const name = host.querySelector('.fm-label-name input');
    expect(host.querySelector('.fm-label-name').hidden).toBe(false);
    expect(name.placeholder).toBe('Green');
    name.value = 'Garden';
    [...host.querySelectorAll('button')].find((b) => b.textContent === 'Save').click();
    await vi.waitFor(() => expect(document.getElementById('fm-label-picker')).toBeNull());
    expect(put.mock.calls[0]).toEqual(['/api/fs/labels/names', { colour: 'green', name: 'Garden' }]);
    expect(put.mock.calls[1]).toEqual(['/api/fs/labels', { path: '/mnt/user/new.txt', colour: 'green' }]);

    const again = openLabelPicker({ path: '/mnt/user/docs/tax.pdf', name: 'tax.pdf' });
    expect(again.querySelector('[data-colour="red"]').getAttribute('aria-pressed')).toBe('true');
    [...again.querySelectorAll('button')].find((b) => b.textContent === 'No label').click();
    await vi.waitFor(() => expect(document.getElementById('fm-label-picker')).toBeNull());
    expect(put.mock.calls.at(-1)).toEqual(['/api/fs/labels', { path: '/mnt/user/docs/tax.pdf', colour: null }]);
  });

  it('the picker closes without a choice, with Escape, the backdrop and its button', async () => {
    const put = vi.spyOn(api, 'put');
    let host = openLabelPicker({ path: '/a', name: 'a' });
    [...host.querySelectorAll('button')].find((b) => b.textContent === 'Save').click();
    await vi.waitFor(() => expect(document.getElementById('fm-label-picker')).toBeNull());
    expect(put).not.toHaveBeenCalled();
    host = openLabelPicker({ path: '/a', name: 'a' });
    host.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }));
    host.querySelector('.smart-modal-window').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(document.getElementById('fm-label-picker')).not.toBeNull();
    host.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(document.getElementById('fm-label-picker')).toBeNull();
    host = openLabelPicker({ path: '/a', name: 'a' });
    host.click();
    expect(document.getElementById('fm-label-picker')).toBeNull();
    host = openLabelPicker({ path: '/a', name: 'a' });
    host.querySelector('.close-btn').click();
    expect(document.getElementById('fm-label-picker')).toBeNull();
  });

  it('a colour in the sidebar lists what carries it and opens the folder', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(VIEW);
    await loadLabels();
    const fm = { loadPath: vi.fn() };
    const host = openLabelList('red', fm);
    expect(host.querySelector('.smart-modal-title').textContent).toBe('Taxes');
    const rows = [...host.querySelectorAll('.fm-label-open')];
    expect(rows.map((r) => r.querySelector('strong').textContent)).toEqual(['a.txt', 'tax.pdf']);
    rows[1].click();
    expect(fm.loadPath).toHaveBeenCalledWith('/mnt/user/docs');
    expect(document.getElementById('fm-label-list')).toBeNull();
    expect(openLabelList('yellow', fm).textContent).toContain('Nothing carries this label.');
  });
});
