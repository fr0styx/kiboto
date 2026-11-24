import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const html = readFileSync(resolve(__dirname, '..', 'windows/management-window.html'), 'utf8');
const pane = html.slice(html.indexOf('id="mgmt-pane-ai-chat"'), html.indexOf('id="mgmt-pane-ai-rag"'));
const css = readFileSync(resolve(__dirname, '..', 'styles/45-ai-history.css'), 'utf8');

describe('Ask Kib in the design language', () => {
  it('uses the shared buttons and badge, not colours of its own', () => {
    expect(pane).toMatch(/id="btn-ai-chat-send" class="btn-pill-toggle is-primary kib-send">/);
    expect(pane).toMatch(/id="btn-ai-chat-stop" class="btn-pill-toggle is-danger kib-send"/);
    expect(pane).toContain('id="ai-chat-active-model-badge" class="kib-model-badge"');
    expect(pane).not.toMatch(/linear-gradient|99,\s*102,\s*241/);
  });

  it('greets an empty conversation with Kib', () => {
    expect(pane).toContain('class="kib-chat-empty"');
    expect(pane).toContain('data-i18n="kibw.empty_line"');
    expect(css).toMatch(/:has\(#ai-chat-messages-list:empty\) #ai-chat-messages-list \{ display: none !important; \}/);
    expect(css).toMatch(/:has\(#ai-chat-messages-list:empty\) \.kib-chat-empty \{ display: flex; \}/);
  });
});
