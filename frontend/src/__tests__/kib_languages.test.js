// SET-26 five-language screenshots: what stayed English in the Kib window.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { shownTitle, putTitle, initAiConversationControls, createNewAiConversation, renameAiConversation } from '../components/management/ai.js';
import { applyTranslations, setLanguage } from '../i18n.js';
import { api } from '../api.js';

describe('Kib window in other languages', () => {
  beforeEach(async () => { await setLanguage('en'); });
  afterEach(async () => { vi.restoreAllMocks(); await setLanguage('en'); });

  it('shows the stored default title in the reader\'s language, and real titles as they are', async () => {
    expect(shownTitle('New Conversation')).toBe('New Conversation');
    expect(shownTitle('')).toBe('New Conversation');
    await setLanguage('de');
    expect(shownTitle('New Conversation')).toBe('Neue Unterhaltung');
    expect(shownTitle(null)).toBe('Neue Unterhaltung');
    expect(shownTitle('Urlaub 2025')).toBe('Urlaub 2025');
    expect(() => putTitle(null, 'x')).not.toThrow(); // no header in the page: nothing to write
  });

  it('an icon button named from its English title is renamed with the title', async () => {
    document.body.innerHTML = `<button id="b" title="Rename conversation" aria-label="Rename conversation" data-i18n-title="ui.rename_conversation"></button>
      <button id="c" title="Rename conversation" aria-label="Own name" data-i18n-title="ui.rename_conversation"></button>
      <button id="d" title="Rename conversation" aria-label="Rename conversation" data-i18n-title="ui.rename_conversation" data-i18n-aria-label="ai.conversation_label"></button>`;
    await setLanguage('de');
    applyTranslations();
    expect(document.getElementById('b').getAttribute('title')).toBe('Unterhaltung umbenennen');
    expect(document.getElementById('b').getAttribute('aria-label')).toBe('Unterhaltung umbenennen');
    expect(document.getElementById('c').getAttribute('aria-label')).toBe('Own name');
    expect(document.getElementById('d').getAttribute('aria-label')).toBe('Unterhaltung'); // its own key wins
  });

  it('a new chat, the count and a rename show in the reader\'s language', async () => {
    document.body.innerHTML = `<button id="btn-ai-chat-new"></button><button id="btn-ai-chat-rename"></button>
      <span id="ai-chat-active-title">New Conversation</span><div id="ai-chat-threads-list"></div>
      <span id="ai-chat-thread-count"></span><div id="ai-chat-messages-list"></div><input id="ai-chat-input">`;
    await setLanguage('de');
    let convs = [];
    vi.spyOn(api, 'get').mockImplementation(async () => ({ status: 'ok', conversations: convs }));
    const post = vi.spyOn(api, 'post').mockImplementation(async () => ({ conversation: { id: 'n1', title: 'New Conversation' } }));
    const patch = vi.spyOn(api, 'patch').mockImplementation(async () => ({ status: 'ok' }));
    initAiConversationControls();
    const title = document.getElementById('ai-chat-active-title');
    title.textContent = 'x';
    await createNewAiConversation();
    expect(post).toHaveBeenCalled();
    expect(title.textContent).toBe('Neue Unterhaltung');
    expect(document.getElementById('ai-chat-thread-count').textContent).toBe('0 Chats');
    convs = [{ id: 'n1', title: 'Urlaub', updated_at: Date.now() / 1000 }];
    await renameAiConversation('n1', 'Urlaub');
    expect(patch).toHaveBeenCalledWith('/api/ai/conversations/n1', { title: 'Urlaub' });
    expect(title.textContent).toBe('Urlaub');
    expect(document.getElementById('ai-chat-thread-count').textContent).toBe('1 Chat');
  });
});
