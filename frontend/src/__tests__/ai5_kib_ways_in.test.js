/** AI 5: every way into Ask Kib opens the Kib window: the dock, "Open Kib" in Settings, a family member's link. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { KNOWN_APPS } from '../components/dock/apps.js';

const kibApp = () => Object.values(KNOWN_APPS).find((a) => a.icon === '#i-kib');
import { bindOpenKib } from '../components/management/ai.js';
import { ROUTES } from '../router.js';
import { TILES } from '../components/phone-shell.js';
import { ROUTE_SCOPES } from '../route-access.js';

vi.mock('../toast.js', () => ({ showToast: vi.fn(), showConfirmToast: vi.fn(), showPromptToast: vi.fn(), showBottomSheet: vi.fn() }));

describe('ways into the Kib window (AI 5)', () => {
  afterEach(() => { delete window.openKibWindow; delete window.openManagementWindow; });

  it('the dock\'s Kib opens the window, or Settings on an older page', () => {
    window.openKibWindow = vi.fn();
    kibApp().launch();
    expect(window.openKibWindow).toHaveBeenCalledWith('mgmt-pane-ai-chat');
    delete window.openKibWindow;
    window.openManagementWindow = vi.fn();
    kibApp().launch();
    expect(window.openManagementWindow).toHaveBeenCalledWith('mgmt-sec-ai-rag', 'mgmt-pane-ai-rag');
  });

  it('"Open Kib" in Settings opens it on Ask, bound once', () => {
    document.body.innerHTML = '<button data-kib-open>Open Kib</button>';
    window.openKibWindow = vi.fn();
    bindOpenKib();
    bindOpenKib();
    document.querySelector('[data-kib-open]').click();
    expect(window.openKibWindow).toHaveBeenCalledTimes(1);
    expect(window.openKibWindow).toHaveBeenCalledWith('mgmt-pane-ai-chat');
    delete window.openKibWindow;
    document.querySelector('[data-kib-open]').click(); // before the window code exists nothing breaks
  });

  it('a phone has an "Ask Kib" tile for everyone, which opens the window', () => {
    const routes = TILES().map(([r]) => r);
    expect(routes.indexOf('ask')).toBe(routes.indexOf('apps') + 1);
    expect(ROUTE_SCOPES.ask).toBeUndefined(); // open to every role; the window says when Kib is off for you
    window.openKibWindow = vi.fn();
    ROUTES.ask();
    expect(window.openKibWindow).toHaveBeenCalledWith('mgmt-pane-ai-chat');
  });
});
