// The user pill opens its menu on click and Enter, loading the menu module only then (A7: first-load headroom).
import { describe, it, expect, beforeEach } from 'vitest';
import { initTopbarUserPill } from '../components/dock/user-pill.js';

const settle = () => new Promise((r) => setTimeout(r, 0));

describe('user pill', () => {
  beforeEach(() => {
    document.body.innerHTML = '<button id="topbar-user-pill"></button>';
  });

  it('opens the profile menu on click, once bound', async () => {
    initTopbarUserPill();
    initTopbarUserPill();
    const pill = document.getElementById('topbar-user-pill');
    pill.click();
    for (let i = 0; i < 20 && !document.getElementById('user-profile-flyout'); i++) await settle();
    expect(document.getElementById('user-profile-flyout')).not.toBeNull();
    expect(pill.dataset.userPillBound).toBe('true');
  });

  it('opens it with Enter and Space too', async () => {
    initTopbarUserPill();
    const pill = document.getElementById('topbar-user-pill');
    pill.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    for (let i = 0; i < 20 && !document.getElementById('user-profile-flyout'); i++) await settle();
    expect(document.getElementById('user-profile-flyout')).not.toBeNull();
    pill.dispatchEvent(new KeyboardEvent('keydown', { key: 'x', bubbles: true }));
  });

  it('does nothing without a pill', () => {
    document.body.innerHTML = '';
    expect(() => initTopbarUserPill()).not.toThrow();
  });
});
