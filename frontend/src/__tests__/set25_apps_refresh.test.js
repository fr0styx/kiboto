/** SET-25 Apps 2b: after an install the Apps window is asked to reload its list (the hidden page's
 *  table used to be redrawn, which still fetched the list). */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { openAppDeployModal } from '../components/management.js';
import { api } from '../api.js';
import { ZettEventBus } from '../event-bus.js';

describe('an install refreshes the Apps window (SET-25)', () => {
  afterEach(() => {
    const modal = document.getElementById('app-deploy-modal-overlay');
    if (modal && modal._close) modal._close();
    vi.restoreAllMocks();
  });

  it('a finished install sends docker:containers:refresh', async () => {
    document.body.innerHTML = '<div id="desktop"></div><div id="os-dock-container"><div id="os-dock"></div></div>';
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/resolve'))
        return { app_id: 'uptime-kuma', default_port: 3001, suggested_port: 3001, conflict_detected: false };
      if (url.includes('/check_port')) return { port: 3001, proto: 'tcp', available: true };
      return {
        apps: [
          { id: 'uptime-kuma', name: 'Uptime Kuma', default_port: 3001, category: 'utilities', description: 'Monitor' },
        ],
      };
    });
    vi.spyOn(api, 'request').mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        [
          JSON.stringify({ step: 'init', percent: 10, message: 'Pulling' }),
          JSON.stringify({ step: 'success', percent: 100, message: 'Running', port: 3001 }),
        ].join('\n'),
    });
    const heard = vi.fn();
    ZettEventBus.on('docker:containers:refresh', heard);
    await openAppDeployModal('uptime-kuma');
    await /** @type {any} */ (document.getElementById('adm-deploy-confirm-btn')).onclick();
    await vi.waitFor(() => expect(heard).toHaveBeenCalled());
    ZettEventBus.off?.('docker:containers:refresh', heard);
  });
});
