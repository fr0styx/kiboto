import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { answerTime } from '../components/management/ai.js';

const panes = readFileSync(resolve(__dirname, '..', 'styles/64-mgmt-panes.css'), 'utf8');
const history = readFileSync(resolve(__dirname, '..', 'styles/45-ai-history.css'), 'utf8');
const ai = readFileSync(resolve(__dirname, '..', 'components/management/ai.js'), 'utf8');

describe("an answer's details in the Kib window", () => {
  it('styles the Kib panes in their own window too, not only inside Settings', () => {
    expect(panes).not.toMatch(/#management-modal-overlay \.(aik|aicm|airg|aimd)-/);
    expect(panes).toContain(':is(#management-modal-overlay, #kib-window) .aicm-size {');
  });

  it('says how long an answer took in seconds from one second up', () => {
    expect(answerTime(45820.4)).toBe('45.8 s');
    expect(answerTime(19.4)).toBe('19 ms');
    expect(answerTime(undefined)).toBe('0 ms');
  });

  it('shows the model in the window colours and no accelerator that was not reported', () => {
    expect(history).toMatch(/\.ai-chat-model-pill \{[^}]*rgba\(var\(--c-primary-rgb\), 0\.12\)/);
    expect(ai).toContain("llmTel.accelerator_tier ? llmTel.accelerator_label || '' : ''");
    expect(ai).not.toMatch(/168,\s*85,\s*247/);
  });
});
