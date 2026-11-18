import { describe, it, expect, vi } from 'vitest';
import { windowPane } from './helpers/window-pane.js';
import { setAiChatFocus, aiChatFocus, askKibAbout } from '../components/management/ai.js';

describe('Ask Kib about this (missing feature 6)', () => {
  it('shows what the questions are about and can drop it', () => {
    document.body.innerHTML = windowPane('mgmt-pane-ai-chat'); // the real markup (SET-26)
    setAiChatFocus('/mnt/user/docs/plan.txt');
    expect(aiChatFocus()).toEqual({ path: '/mnt/user/docs/plan.txt', name: 'plan.txt' });
    const chip = document.getElementById('ai-chat-focus');
    expect(chip.textContent).toContain('plan.txt');
    chip.querySelector('button').click();
    expect(aiChatFocus()).toBeNull();
    expect(document.getElementById('ai-chat-focus')).toBeNull();
  });

  it('opens the chat with the file in focus', async () => {
    vi.useFakeTimers();
    document.body.innerHTML = windowPane('mgmt-pane-ai-chat'); // the real markup (SET-26)
    window.openManagementSection = vi.fn();
    askKibAbout('/mnt/user/docs/plan.txt', 'plan.txt');
    vi.advanceTimersByTime(400);
    expect(window.openManagementSection).toHaveBeenCalledWith('mgmt-sec-ai', 'mgmt-pane-ai-chat');
    expect(document.getElementById('ai-chat-input').placeholder).toContain('plan.txt');
    expect(window.askKibAbout).toBe(askKibAbout);
    vi.useRealTimers();
    setAiChatFocus(null);
  });
});

describe('the chat request carries the file in focus', () => {
  it('sends focus_path with the question', async () => {
    const { api } = await import('../api.js');
    const { sendAiChatMessage } = await import('../components/management/ai.js');
    document.body.innerHTML = windowPane('mgmt-pane-ai-chat'); // the real markup (SET-26)
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ reply: 'It says 42.', tools_called: [] });
    setAiChatFocus('/mnt/user/docs/plan.txt');
    await sendAiChatMessage('What is the budget?');
    expect(post).toHaveBeenCalledWith(
      '/api/media/chat',
      expect.objectContaining({ message: 'What is the budget?', focus_path: '/mnt/user/docs/plan.txt' })
    );
    post.mockRestore();
    setAiChatFocus(null);
  });
});
