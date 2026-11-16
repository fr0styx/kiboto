import { describe, it, expect, vi, afterEach } from 'vitest';
import markup from '../windows/management-window.html?raw';
import { api } from '../api.js';
import { fetchAndRenderNotificationConfig, testAllNotificationChannels } from '../components/management/notifications.js';
import { renderFrigateEvents } from '../components/frigate-events.js';

vi.mock('../components/my-alerts.js', () => ({ renderMyAlerts: vi.fn() }));

const pane = () => {
  const doc = new DOMParser().parseFromString(markup, 'text/html');
  return /** @type {HTMLElement} */ (doc.getElementById('mgmt-pane-notifications'));
};

afterEach(() => vi.restoreAllMocks());

describe("Notifications in the report's order (SET-23, cards 2-6)", () => {
  it('Send alerts, this device, where, what, how often, cameras', () => {
    const ids = [...pane().querySelectorAll('[id]')].map((e) => e.id);
    const at = (id) => {
      expect(ids, id).toContain(id);
      return ids.indexOf(id);
    };
    const order = ['notif-master-enabled', 'push-device-card', 'notif-badge-email', 'notif-badge-ntfy', 'notif-more-channels', 'notif-toggle-smart', 'digest-title', 'notif-input-hdd-temp', 'frigate-events-mount']; // Home Assistant moved to Connections (SET-23)
    const pos = order.map(at);
    expect([...pos].sort((a, b) => a - b)).toEqual(pos);
  });

  it('the test sits in Send alerts; webhook and Apprise are folded; the limits live under Fine-tune', () => {
    const p = pane();
    expect(p.querySelector('.nt-send #btn-send-test-alert')).not.toBeNull();
    const more = /** @type {HTMLDetailsElement} */ (p.querySelector('#notif-more-channels'));
    expect(more.open).toBe(false);
    expect(more.querySelector('[data-channel="webhook"]')).not.toBeNull();
    expect(more.querySelector('[data-channel="apprise_raw"]')).not.toBeNull();
    expect(more.querySelector('[data-channel="email"]')).toBeNull();
    const fine = /** @type {HTMLDetailsElement} */ (p.querySelector('details.nt-fine'));
    expect(fine.querySelector('#notif-input-cooldown')).not.toBeNull();
    expect(p.querySelector('[data-i18n="mw.hdd_temp_threshold_c"]')?.textContent).toContain('SATA');
    expect(p.textContent).not.toContain('Alert Channels & Notification Routing');
  });

  it('More opens when one of its services is in use', async () => {
    document.body.innerHTML = '<input type="checkbox" id="notif-master-enabled"><details id="notif-more-channels"></details>';
    vi.spyOn(api, 'get').mockResolvedValue({ enabled: true, webhook_enabled: true, webhook_url: 'http://x' });
    await fetchAndRenderNotificationConfig();
    expect(/** @type {HTMLDetailsElement} */ (document.getElementById('notif-more-channels')).open).toBe(true);
    document.body.innerHTML = '<details id="notif-more-channels"></details>';
    vi.spyOn(api, 'get').mockResolvedValue({ enabled: true });
    await fetchAndRenderNotificationConfig();
    expect(/** @type {HTMLDetailsElement} */ (document.getElementById('notif-more-channels')).open).toBe(false);
  });

  it('the test button says what it does before and after', async () => {
    document.body.innerHTML = '<button id="btn-send-test-alert">Send a test</button>';
    vi.spyOn(api, 'post').mockResolvedValue({ tested_channels: { email: true } });
    await testAllNotificationChannels();
    const btn = /** @type {HTMLButtonElement} */ (document.getElementById('btn-send-test-alert'));
    expect(btn.textContent).toBe('Send a test');
    expect(btn.disabled).toBe(false);
  });

  it('Cameras shows only when Frigate runs here or its alerts are on', async () => {
    const base = { url: 'http://frigate:5000', labels: [], cameras: [], min_score: 0.7, cooldown_min: 5, choices: [] };
    document.body.innerHTML = '<section id="cams"><div id="m"></div></section>';
    const card = /** @type {HTMLElement} */ (document.getElementById('cams'));
    const mount = /** @type {HTMLElement} */ (document.getElementById('m'));
    vi.spyOn(api, 'get').mockResolvedValueOnce({ ...base, enabled: false, installed: false });
    await renderFrigateEvents(mount);
    expect(card.hidden).toBe(true);
    vi.spyOn(api, 'get').mockResolvedValueOnce({ ...base, enabled: false, installed: true });
    await renderFrigateEvents(mount);
    expect(card.hidden).toBe(false);
    vi.spyOn(api, 'get').mockResolvedValueOnce({ ...base, enabled: true, installed: false });
    await renderFrigateEvents(mount);
    expect(card.hidden).toBe(false);
  });
});
