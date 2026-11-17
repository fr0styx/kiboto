// SET-31, X5 d: "Restart or shut down" in the person menu of the top bar, for people who may do it.
import { describe, it, expect, vi } from 'vitest';

let scopes = ['system:power'];
vi.mock('../route-access.js', () => ({
  currentUser: () => ({ scopes }),
  hasScope: (have, want) => have.includes(want),
}));

vi.mock('../components/session.js', () => ({ updateUserInterfaceElements: () => {} }));
vi.mock('../components/auth.js', () => ({ lockDesktop: () => {}, switchUser: () => {}, logout: () => {} }));

const { toggleUserProfileFlyout } = await import('../components/dock/user-flyout.js');
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('restart or shut down in the person menu', () => {
  it('shows for someone who may switch the NAS and opens Power', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout'] });
    document.body.innerHTML = '<button id="pill"></button><section id="power-switch"></section>';
    const opened = [];
    /** @type {any} */ (window).openManagementWindow = (pane) => opened.push(pane);
    toggleUserProfileFlyout(document.getElementById('pill'));
    vi.useRealTimers();
    await flush();
    await flush();
    const btn = /** @type {HTMLElement} */ (document.getElementById('btn-flyout-power'));
    expect(btn.hidden).toBe(false);
    btn.click();
    expect(opened).toEqual(['mgmt-sec-ups']);
    await new Promise((r) => setTimeout(r, 1000)); // the scroll to the section runs after the pane opens
  });

  it('stays hidden for everyone else', async () => {
    scopes = ['shares:read'];
    document.getElementById('user-profile-flyout')?.remove();
    document.body.innerHTML = '<button id="pill2"></button>';
    toggleUserProfileFlyout(document.getElementById('pill2'));
    await flush();
    await flush();
    expect(/** @type {HTMLElement} */ (document.getElementById('btn-flyout-power')).hidden).toBe(true);
  });
});
