// The paths the type clean-up touched (numbers now written as strings, event targets cast) still do
// what they did: LED looks set their sliders, the install window fills its port, the person menu
// closes on a click outside.
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../route-access.js', () => ({ currentUser: () => ({ scopes: [] }), hasScope: () => false }));
vi.mock('../components/session.js', () => ({ updateUserInterfaceElements: () => {} }));
vi.mock('../components/auth.js', () => ({ lockDesktop: () => {}, switchUser: () => {}, logout: () => {} }));

const { api } = await import('../api.js');
const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = '';
});

describe('LED looks', () => {
  it('each look sets brightness and speed, and sends them as numbers', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ power: 'on', mode: 'solid', color: '25c2a0' });
    const post = vi.spyOn(api, 'post').mockResolvedValue({});
    document.body.innerHTML = `<div id="tab-led">
      ${['clean', 'cyberpunk', 'stealth', 'rainbow'].map((p) => `<button class="profile-pill" data-profile="${p}"></button>`).join('')}
      </div><input id="led-slider" type="range" min="0" max="100" value="50">
      <input id="speed-slider" type="range" min="0" max="100" value="50"><span id="led-val-display"></span>`;
    const { initLedControl } = await import('../components/led-control.js');
    initLedControl();
    await flush();
    const pill = (p) => /** @type {HTMLElement} */ (document.querySelector(`[data-profile="${p}"]`));
    const sent = () => post.mock.calls.filter(([url]) => url === '/api/led').pop()[1];
    const cases = [
      ['clean', 25, 50],
      ['cyberpunk', 40, 65],
      ['stealth', 8, 65],
      ['rainbow', 35, 70],
    ];
    for (const [look, bri, speed] of cases) {
      pill(look).click();
      await flush();
      expect(/** @type {HTMLInputElement} */ (document.getElementById('led-slider')).value).toBe(String(bri));
      expect(sent()).toMatchObject({ brightness: bri, speed });
      expect(document.getElementById('led-val-display').textContent).toBe(`${bri}%`);
    }
  });

  it('without sliders it sends the defaults', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ power: 'on', mode: 'solid' });
    const post = vi.spyOn(api, 'post').mockResolvedValue({});
    document.body.innerHTML = `<div id="tab-led">${['clean', 'cyberpunk', 'stealth', 'rainbow']
      .map((p) => `<button class="profile-pill" data-profile="${p}"></button>`)
      .join('')}</div>`;
    const { initLedControl } = await import('../components/led-control.js');
    initLedControl();
    await flush();
    for (const pill of document.querySelectorAll('.profile-pill')) {
      pill.click();
      await flush();
      expect(post).toHaveBeenLastCalledWith('/api/led', expect.objectContaining({ brightness: 25, speed: 50 }));
    }
  });
});

describe('install window port', () => {
  afterEach(() => {
    const modal = document.getElementById('app-deploy-modal-overlay');
    if (modal && modal._close) modal._close();
  });
  const open = async (resolve) => {
    document.body.innerHTML = '<div id="os-dock-container"><div id="os-dock"></div></div>';
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/resolve')) {
        if (resolve instanceof Error) throw resolve;
        return resolve;
      }
      if (url.includes('check_container_name')) return { exists: false };
      if (url.includes('check_port')) return { available: true };
      return { apps: [{ id: 'uptime-kuma', name: 'Uptime Kuma', default_port: 3001 }] };
    });
    vi.spyOn(api, 'request').mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ default_port: 3001, compose_yaml: 'x: 1' }),
    });
    const { openAppDeployModal } = await import('../components/management.js');
    await openAppDeployModal('uptime-kuma');
    return /** @type {HTMLInputElement} */ (document.getElementById('adm-port-input'));
  };

  it('a taken port: the free one it suggests', async () => {
    const port = await open({
      app_id: 'uptime-kuma',
      default_port: 3001,
      suggested_port: 3002,
      conflict_detected: true,
      in_use_by: 'x',
    });
    await vi.waitFor(() => expect(port.value).toBe('3002'));
  });

  it('when the check fails: 8080', async () => {
    const port = await open(new Error('offline'));
    await vi.waitFor(() => expect(port.value).toBe('8080'));
  });
});

describe('person menu', () => {
  it('closes on a click outside it, not on a click inside', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout'] });
    document.body.innerHTML =
      '<button id="pill"></button><button id="topbar-user-pill"></button><button id="elsewhere"></button>';
    const { toggleUserProfileFlyout } = await import('../components/dock/user-flyout.js');
    toggleUserProfileFlyout(document.getElementById('pill'));
    vi.useRealTimers();
    await flush();
    await flush();
    const flyout = document.getElementById('user-profile-flyout');
    expect(flyout.style.display).not.toBe('none');
    for (const inside of [flyout, document.getElementById('pill'), document.getElementById('topbar-user-pill')]) {
      inside.click();
      expect(flyout.style.display).not.toBe('none');
    }
    document.getElementById('elsewhere').click();
    expect(flyout.style.display).toBe('none');
  });
});

describe('dock magnification', () => {
  it('takes a number or a numeric text, and falls back to 1.45', async () => {
    const dock = await import('../components/dock/dock-settings.js');
    for (const [given, want] of [
      [1.6, 1.6],
      ['1.3', 1.3],
      [undefined, 1.45],
      ['big', 1.45],
      [9, 1.8],
    ]) {
      dock.applyDockSettings('bottom', true, given, 'medium', false, false);
      expect(dock.getDockSettings().scale).toBe(want);
    }
  });
});

describe('desktop right-click', () => {
  it('a right-click on the document itself (no element) is left to the browser', async () => {
    const m = await import('../components/desktop-context-menu.js');
    m.initDesktopContextMenu();
    const ev = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
    document.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
  });
});
