// Kib on the desktop: its face floats in a corner and opens Kib's own window.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { initKibBuddy, openKib } from '../components/kib-buddy.js';

describe('Kib on the desktop', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    delete (/** @type {any} */ (window).openKibWindow);
  });

  it('puts the face there once, named for screen readers', () => {
    const btn = initKibBuddy();
    expect(btn.id).toBe('kib-buddy');
    expect(btn.getAttribute('aria-label')).toBe('Ask Kib');
    expect(btn.querySelector('.kib-buddy-label').textContent).toBe('Ask Kib');
    expect(btn.querySelectorAll('.kib-buddy-eye')).toHaveLength(2);
    expect(initKibBuddy()).toBe(btn);
    expect(document.querySelectorAll('#kib-buddy')).toHaveLength(1);
  });

  it("opens Kib's own window on its chat, not Settings", () => {
    const open = vi.fn();
    /** @type {any} */ (window).openKibWindow = open;
    initKibBuddy().click();
    expect(open).toHaveBeenCalledWith('mgmt-pane-ai-chat');
  });

  it('does nothing before Kib can be opened', () => {
    expect(() => openKib(/** @type {any} */ ({}))).not.toThrow();
  });
});
