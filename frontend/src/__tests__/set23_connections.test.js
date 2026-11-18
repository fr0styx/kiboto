import { describe, it, expect, vi, afterEach } from 'vitest';
import markup from '../windows/management-window.html?raw';
import { api } from '../api.js';
import { ROUTES } from '../router.js';
import { renderRedfishCard } from '../components/management/connections.js';

afterEach(() => vi.restoreAllMocks());

const doc = () => new DOMParser().parseFromString(markup, 'text/html');

describe('Connections, an Advanced page (SET-23, Settings decision 8)', () => {
  it('holds Home Assistant, API tokens, sign-in and Redfish; the old places do not', () => {
    const d = doc();
    const pane = /** @type {HTMLElement} */ (d.getElementById('mgmt-pane-connections'));
    for (const id of [
      'notif-ha-grid',
      'api-tokens-list',
      'new-token-name',
      'sec-sso-card',
      'sec-ldap-card',
      'conn-redfish-card',
    ]) {
      expect(pane.querySelector(`#${id}`), id).not.toBeNull();
    }
    expect(d.getElementById('mgmt-pane-security')?.querySelector('#sec-sso-card')).toBeNull();
    expect(d.getElementById('mgmt-pane-notifications')?.querySelector('#notif-ha-grid')).toBeNull();
    expect(d.getElementById('mgmt-pane-account')?.querySelector('#api-tokens-list')).toBeNull();
    expect(d.getElementById('mgmt-pane-account')?.querySelector('#acc-open-connections')).not.toBeNull();
    const item = /** @type {HTMLElement} */ (d.querySelector('.mgmt-sidebar-item[data-route="connections"]'));
    expect(item.dataset.mgmtPane).toBe('mgmt-pane-connections');
    expect(item.dataset.group).toBe('advanced');
  });

  it('#/connections opens it', () => {
    const open = vi.fn();
    /** @type {any} */ (window).openManagementSection = open;
    ROUTES.connections();
    expect(open).toHaveBeenCalledWith('mgmt-pane-connections');
  });

  it('the Redfish switch reads, turns on and says so, and puts itself back when that fails', async () => {
    const mount = document.createElement('div');
    vi.spyOn(api, 'get').mockResolvedValue({ enabled: false });
    const put = vi.spyOn(api, 'put').mockResolvedValue({ enabled: true });
    await renderRedfishCard(mount);
    const box = /** @type {HTMLInputElement} */ (mount.querySelector('input[type="checkbox"]'));
    expect(box.checked).toBe(false);
    expect(mount.textContent).toContain('Redfish for monitoring tools');
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(box.disabled).toBe(false));
    expect(put).toHaveBeenCalledWith('/api/system/redfish', { enabled: true });
    expect(box.checked).toBe(true);
    put.mockRejectedValueOnce(new Error('no right'));
    box.checked = false;
    box.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(box.disabled).toBe(false));
    expect(box.checked).toBe(true);
  });

  it('says when it cannot read the switch', async () => {
    const mount = document.createElement('div');
    vi.spyOn(api, 'get').mockRejectedValue(new Error('x'));
    await renderRedfishCard(mount);
    expect(mount.textContent).toBe("Couldn't read whether Redfish is on.");
    await renderRedfishCard(null);
  });
});
