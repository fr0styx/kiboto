// Re-audit R3: History -> "Save as a file".
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { showToast } from '../toast.js';
import { csvCell, eventsCsv, exportHistory, saveText } from '../components/history-export.js';
import { renderEventLog } from '../components/events.js';

vi.mock('../toast.js', async (orig) => ({ ...(await orig()), showToast: vi.fn() }));

const view = (e) => ({ title: e.title, message: e.message });

describe('History export', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('quotes what needs it and defuses formulas', () => {
    expect(csvCell('Backup finished')).toBe('Backup finished');
    expect(csvCell('a, b')).toBe('"a, b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell('=1+1')).toBe("'=1+1");
    expect(csvCell('-5 °C')).toBe("'-5 °C");
    expect(csvCell(null)).toBe('');
    expect(csvCell(3)).toBe('3');
  });

  it('writes one line per entry with a heading, as the list shows them', () => {
    const csv = eventsCsv(
      [
        { ts: 1763500000, title: 'Backup failed', message: 'The copy, to USB, stopped.' },
        { ts: 1763400000, last_ts: 1763490000, title: 'Drive is warm', message: 'sda reached 52 °C.', count: 3 },
      ],
      view
    );
    const lines = csv.trim().split('\r\n');
    expect(lines[0]).toBe('When,What happened,Details,Times');
    expect(lines[1]).toMatch(/,Backup failed,"The copy, to USB, stopped\.",1$/);
    expect(lines[2]).toMatch(/,Drive is warm,sda reached 52 °C\.,3$/);
    expect(eventsCsv(null, view)).toBe('When,What happened,Details,Times\r\n');
  });

  it('saves the list on screen as a file, and Sign-ins from the server', async () => {
    const made = [];
    vi.spyOn(URL, 'createObjectURL').mockImplementation((b) => {
      made.push(b);
      return 'blob:x';
    });
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    expect(await exportHistory({ events: [{ ts: 1, title: 'x', message: 'y' }], view })).toBe(true);
    expect(clicked).toHaveBeenCalledTimes(1);
    expect(made[0].type).toContain('text/csv');
    const dl = vi.spyOn(api, 'downloadBlob').mockResolvedValue(undefined);
    expect(await exportHistory({ filter: 'signins', view })).toBe(true);
    expect(dl.mock.calls[0][0]).toBe('/api/auth/audit/export');
    saveText('a.csv', 'x'); // also on its own
    expect(clicked).toHaveBeenCalledTimes(2);
  });

  it('says so when the file cannot be saved', async () => {
    vi.spyOn(api, 'downloadBlob').mockRejectedValue(new Error('no right'));
    expect(await exportHistory({ filter: 'signins', view })).toBe(false);
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('no right'), 'error');
  });

  it('the History bar has the button; it is hidden on Files', async () => {
    document.body.innerHTML = '<div><div id="events-list"></div></div>';
    renderEventLog([
      { id: 1, ts: Math.floor(Date.now() / 1000), level: 'info', title: 'Backup finished', message: 'm' },
    ]);
    const bar = document.querySelector('.history-controls');
    const button = /** @type {HTMLButtonElement} */ (bar.querySelector('.history-export'));
    expect(button.textContent).toBe('Save as a file');
    /** @type {HTMLElement} */ (bar.querySelector('[data-filter="files"]')).click();
    expect(button.hidden).toBe(true);
    /** @type {HTMLElement} */ (bar.querySelector('[data-filter="all"]')).click();
    expect(button.hidden).toBe(false);
    const made = [];
    vi.spyOn(URL, 'createObjectURL').mockImplementation((b) => {
      made.push(b);
      return 'blob:x';
    });
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    button.click();
    await vi.waitFor(() => expect(made.length).toBe(1));
  });
});
