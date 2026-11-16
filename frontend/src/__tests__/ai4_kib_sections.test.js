/** AI 4: Kib settings in the report's order, with "Who can use Kib" and a Privacy list from the real settings. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { onThisNas, privacyLines, renderKibPrivacy } from '../components/management/kib-privacy.js';
import { loadKibPrivacy } from '../components/management/ai.js';
import { installAiAccess } from '../components/management/ai-access.js';
import { api } from '../api.js';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

const HTML = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');

describe('Kib settings sections (AI 4)', () => {
  beforeEach(() => { document.body.innerHTML = ''; });
  afterEach(() => vi.restoreAllMocks());

  it('puts status, folders, who and privacy first, and folds the rest under Advanced', () => {
    const pane = HTML.slice(HTML.indexOf('id="mgmt-pane-ai-index"'));
    const at = (s) => pane.indexOf(s);
    expect(at('id="kib-status-mount"')).toBeLessThan(at('id="kib-folders-h"'));
    expect(at('id="kib-folders-h"')).toBeLessThan(at('id="kib-who-h"'));
    expect(at('id="kib-who-h"')).toBeLessThan(at('id="kib-privacy-h"'));
    expect(at('id="kib-privacy-h"')).toBeLessThan(at('id="kib-advanced"'));
    for (const inside of ['id="ai-llm-recommendations-section"', 'mw.search_index_model_and_size', 'ai.config_policy_title', 'aria-labelledby="ai-pack-title"']) {
      expect(at(inside)).toBeGreaterThan(at('id="kib-advanced"'));
    }
    expect(at('ai.config_history_title')).toBeGreaterThan(at('id="kib-privacy-h"'));
    expect(at('ai.config_history_title')).toBeLessThan(at('id="kib-advanced"'));
  });

  it('knows which addresses are on this NAS', () => {
    for (const u of ['http://localhost:11434', 'http://127.0.0.1:8000', 'http://kiboto-ovms:9000', 'http://[::1]:1', 'http://host.docker.internal:1']) expect(onThisNas(u)).toBe(true);
    for (const u of ['https://api.example.com/v1', 'http://192.168.1.20:11434', 'not a url']) expect(onThisNas(u)).toBe(false);
  });

  it('lists web lookups, then each outside address with what it gets', () => {
    expect(privacyLines()).toEqual(['Web lookups: off unless a chat turns them on; that choice is not remembered.']);
    const lines = privacyLines({ llm_endpoint: 'http://kiboto-ovms:9000', embedding_host: 'https://embed.example.com/v1', rerank_endpoint: 'http://192.168.1.5:7997', photo_vector_host: 'odd', transcribe_endpoint: '' });
    expect(lines.slice(1)).toEqual([
      'embed.example.com gets: text from your files, to turn it into search vectors.',
      '192.168.1.5:7997 gets: search questions and the best results, for a second check.',
      'odd gets: small copies of your photos, to find them by what is in them.',
    ]);
    const all = privacyLines({ llm_endpoint: 'https://chat.example.com', transcribe_endpoint: 'https://w.example.com' });
    expect(all[1]).toContain('questions and the parts of files that answer them');
    expect(all[2]).toContain('audio from voice memos');
    const ul = document.createElement('ul');
    renderKibPrivacy(ul, {});
    expect(ul.children).toHaveLength(1);
    renderKibPrivacy(null, {});
  });

  it('loads the list once per opening, and tries again after a failure', async () => {
    document.body.innerHTML = '<ul id="kib-privacy-list"></ul>';
    const get = vi.spyOn(api, 'get').mockRejectedValueOnce(new Error('down')).mockResolvedValue({ embedding_host: 'https://e.example.com' });
    await loadKibPrivacy();
    expect(document.getElementById('kib-privacy-list').dataset.loaded).toBeUndefined();
    await loadKibPrivacy();
    expect(document.getElementById('kib-privacy-list').children).toHaveLength(2);
    await loadKibPrivacy();
    expect(get).toHaveBeenCalledTimes(2);
    document.body.innerHTML = '';
    await loadKibPrivacy();
  });

  it('"Who can use Kib" goes into its own section', async () => {
    document.body.innerHTML = '<div id="kib-who-mount"></div><form id="ai-rerank-form"></form>';
    vi.spyOn(api, 'get').mockImplementation(async (url) => (String(url).startsWith('/api/ai/access') ? { roles: [] } : { requests: [] }));
    await installAiAccess(document);
    expect(document.getElementById('kib-who-mount').children.length).toBe(1);
    expect(document.getElementById('ai-rerank-form').nextElementSibling).toBeNull();
    expect(document.querySelector('#kib-who-mount .kb-title')).toBeNull(); // the section heading names it
  });
});
