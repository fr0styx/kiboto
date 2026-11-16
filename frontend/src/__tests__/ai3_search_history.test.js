/** AI 3: recent Kib searches belong to the person who made them, not to the browser. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { aiHistoryKey, renderAiSearchHistory, runAiRagAsk } from '../components/management/ai.js';
import { ZettEventBus } from '../event-bus.js';
import { api } from '../api.js';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

const chips = () => [...document.querySelectorAll('#ai-history-chips button, #ai-history-chips [data-q]')].map((c) => c.textContent.trim());
const signIn = (user) => ZettEventBus.emit('session:user', user);

describe('Kib search history per person (AI 3)', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = '<div id="ai-history-bar"></div><div id="ai-history-chips"></div><input id="ai-rag-query-input"><div id="ai-rag-results"></div>';
    vi.spyOn(api, 'post').mockResolvedValue({ status: 'ok', results: [] });
    vi.spyOn(api, 'get').mockResolvedValue({});
  });
  afterEach(() => vi.restoreAllMocks());

  it('names the key after the person, and has none for nobody', () => {
    expect(aiHistoryKey({ username: 'Ana' })).toBe('kiboto_ai_search_history:ana');
    expect(aiHistoryKey({ id: 7 })).toBe('kiboto_ai_search_history:7');
    expect(aiHistoryKey(null)).toBe('');
    expect(aiHistoryKey({})).toBe('');
  });

  it('the next person does not see what the last one searched for', async () => {
    localStorage.setItem('kiboto_ai_search_history', JSON.stringify(['old shared']));
    signIn({ username: 'ana', scopes: ['*'] });
    await runAiRagAsk('tax letter');
    expect(JSON.parse(localStorage.getItem('kiboto_ai_search_history:ana'))).toEqual(['tax letter']);
    expect(localStorage.getItem('kiboto_ai_search_history')).toBeNull();
    signIn({ username: 'ben', scopes: ['*'] });
    renderAiSearchHistory();
    expect(document.getElementById('ai-history-bar').style.display).toBe('none');
    await runAiRagAsk('holiday');
    expect(JSON.parse(localStorage.getItem('kiboto_ai_search_history:ben'))).toEqual(['holiday']);
    signIn({ username: 'ana', scopes: ['*'] });
    renderAiSearchHistory();
    expect(document.getElementById('ai-history-chips').textContent).toContain('tax letter');
    expect(document.getElementById('ai-history-chips').textContent).not.toContain('holiday');
  });

  it('nobody signed in keeps searches for this page only', async () => {
    signIn(null);
    await runAiRagAsk('pasta');
    expect(Object.keys(localStorage).filter((k) => k.startsWith('kiboto_ai_search_history'))).toEqual([]);
    expect(document.getElementById('ai-history-chips').textContent).toContain('pasta');
  });
});
