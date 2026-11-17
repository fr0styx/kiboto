// Hardware report finding 18: the card copy settings save as they change, Overwrite says what it does,
// and the Card copies tab has no buttons that point at nothing.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import fs from 'fs';
import path from 'path';
import { api } from '../api.js';
import { setLanguage } from '../i18n.js';

const DRAWER = fs.readFileSync(path.resolve(__dirname, '../windows/drawer.html'), 'utf8');
const MW = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');

const FIXTURE = `<div id="management-modal-overlay"></div>
  <input type="checkbox" id="btn-copy-toggle"><div id="btn-copy-options"></div><span id="btn-copy-status-text"></span>
  <select id="btn-copy-src"><option value="sd">SD</option><option value="tf">TF</option></select>
  <input id="btn-copy-dst" value="/mnt/user/photos/">
  <input type="checkbox" id="btn-copy-exif" checked>
  <input type="checkbox" id="btn-copy-auto-ingest">
  <input type="checkbox" id="btn-copy-require-confirm" checked>
  <select id="btn-copy-collision"><option value="skip">Skip</option><option value="overwrite">Overwrite</option><option value="ask">Ask</option></select>
  <p id="btn-copy-overwrite-warn" hidden></p>`;

const $ = (id) => document.getElementById(id);
const change = (el, set) => {
  set(el);
  el.dispatchEvent(new Event('change'));
};
const lastSaved = (post) => post.mock.calls.filter(([url]) => url === '/api/buttons').pop()?.[1];

describe('card copy settings (finding 18)', () => {
  let post;
  beforeEach(async () => {
    document.body.innerHTML = FIXTURE;
    vi.spyOn(api, 'get').mockResolvedValue({ enabled: true, on_collision: 'overwrite', auto_ingest: true, require_confirmation: false });
    post = vi.spyOn(api, 'post').mockResolvedValue({});
    const settings = await import('../components/settings.js');
    settings.initSettings();
  });
  afterEach(async () => {
    vi.restoreAllMocks();
    await setLanguage('en');
    document.body.innerHTML = '';
  });

  it('a stored Overwrite with automatic copying and no question says so when the page opens', async () => {
    await vi.waitFor(() => expect($('btn-copy-overwrite-warn').hidden).toBe(false));
    expect($('btn-copy-overwrite-warn').textContent).toMatch(/starts by itself.*replaced without asking/);
  });

  it('each setting saves the moment it changes', async () => {
    await vi.waitFor(() => expect($('btn-copy-collision').value).toBe('overwrite'));
    change($('btn-copy-auto-ingest'), (el) => { el.checked = false; });
    await vi.waitFor(() => expect(lastSaved(post)).toMatchObject({ auto_ingest: false }));
    change($('btn-copy-require-confirm'), (el) => { el.checked = true; });
    await vi.waitFor(() => expect(lastSaved(post)).toMatchObject({ require_confirmation: true }));
    expect($('btn-copy-overwrite-warn').textContent).toBe("Files with the same name already in the folder are replaced by the card's copy.");
    change($('btn-copy-collision'), (el) => { el.value = 'skip'; });
    await vi.waitFor(() => expect(lastSaved(post)).toMatchObject({ on_collision: 'skip' }));
    expect($('btn-copy-overwrite-warn').hidden).toBe(true);
  });

  it('the warning follows the language', async () => {
    await vi.waitFor(() => expect($('btn-copy-overwrite-warn').hidden).toBe(false));
    await setLanguage('de');
    expect($('btn-copy-overwrite-warn').textContent).toMatch(/ohne Rückfrage ersetzt/);
  });

  it('the markup: no Save button, a warning line, no buttons to the drawer', async () => {
    const { overwriteWarning } = await import('../components/settings.js');
    expect(overwriteWarning(null)).toBe('');
    expect(overwriteWarning({ on_collision: 'ask' })).toBe('');
    expect(DRAWER).not.toContain('id="btn-copy-save"');
    expect(DRAWER).toContain('id="btn-copy-overwrite-warn"');
    expect(MW).not.toContain('btn-open-copy-drawer');
  });
});
