/** Shares R3: "Backups from a Mac" with each folder's size limit and the steps on the Mac. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { timeMachineHtml, renderTimeMachine } from '../components/share-time-machine.js';
import { api } from '../api.js';
import { showToast, showPromptToast } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showPromptToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('Backups from a Mac (Shares R3)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="page"></div><input type="checkbox" id="create-share-timemachine">';
    vi.clearAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());

  it('says what there is, or how to start, and always the steps on the Mac', () => {
    document.body.innerHTML = timeMachineHtml({
      folders: [
        { name: 'macs', size_gb: 500 },
        { name: 'old', size_gb: 0 },
      ],
    });
    expect(document.body.textContent).toContain('macs up to 500 GB');
    expect(document.body.textContent).toContain('old no size limit');
    expect(document.querySelectorAll('.tm-steps li')).toHaveLength(3);
    document.body.innerHTML = timeMachineHtml({ folders: [] });
    expect(document.querySelector('[data-tm-make]').textContent).toBe('Make a folder for Mac backups');
    document.body.innerHTML = timeMachineHtml(null, 'Unraid');
    expect(document.body.textContent).toContain('Unraid makes the folders Macs back up to.');
    expect(document.querySelector('[data-tm-make]')).toBeNull();
  });

  it('change, stop and make work from the page', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ managed: true, folders: [{ name: 'macs', size_gb: 500 }] });
    const put = vi
      .spyOn(api, 'put')
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new Error('denied'))
      .mockResolvedValue({});
    const page = document.getElementById('page');
    await renderTimeMachine(page);
    showPromptToast.mockImplementationOnce((title, msg, def, ok) => ok('800'));
    page.querySelector('[data-tm-size]').click();
    await flush();
    await flush();
    expect(put).toHaveBeenCalledWith('/api/storage/shares/macs/time-machine', { size_gb: 800 });
    expect(showToast).toHaveBeenCalledWith('Macs can now back up to macs, up to 800 GB.', 'success');
    page.querySelector('[data-tm-stop]').click();
    await flush();
    await flush();
    expect(showToast).toHaveBeenLastCalledWith('denied', 'error');
    page.querySelector('[data-tm-stop]').click();
    await flush();
    await flush();
    expect(showToast).toHaveBeenLastCalledWith(
      'Macs no longer back up to macs. The backups already there stay.',
      'success'
    );
    showPromptToast.mockImplementationOnce((title, msg, def, ok) => ok('none'));
    page.querySelector('[data-tm-size]').click();
    expect(put).toHaveBeenCalledTimes(3); // a size that is not a number changes nothing
    get.mockResolvedValue({ managed: true, folders: [] });
    const make = vi.fn();
    await renderTimeMachine(page, '', make);
    page.querySelector('[data-tm-make]').click();
    expect(make).toHaveBeenCalled();
    expect(document.getElementById('create-share-timemachine').checked).toBe(true);
    expect(page.querySelectorAll('#tm-section')).toHaveLength(1);
  });

  it("is left out for someone who does not manage shares, and shown with the host's name", async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('403'));
    const page = document.getElementById('page');
    await renderTimeMachine(page);
    expect(page.querySelector('#tm-section')).toBeNull();
    await renderTimeMachine(page, 'Unraid');
    expect(page.querySelector('#tm-section').textContent).toContain('Unraid makes');
    await renderTimeMachine(null);
  });
});
