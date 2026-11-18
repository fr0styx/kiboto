/** NUX-20: the install window's name and port checks, a failed install, the template check and load errors. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { api } from '../api.js';
import { DockManager } from '../components/dock.js';
import { openAppDeployModal } from '../components/management.js';

const wait = (ms = 320) => new Promise((r) => setTimeout(r, ms));
let answers;

function routes(extra = {}) {
  answers = {
    resolve: { app_id: 'uptime-kuma', default_port: 3001, suggested_port: 3001, conflict_detected: false },
    name: { exists: false },
    port: { available: true },
    ...extra,
  };
  vi.spyOn(api, 'get').mockImplementation(async (url) => {
    if (url.includes('/resolve')) return answers.resolve;
    if (url.includes('check_container_name')) return answers.name;
    if (url.includes('check_port')) return answers.port;
    return { apps: [{ id: 'uptime-kuma', name: 'Uptime Kuma', default_port: 3001 }] };
  });
  vi.spyOn(api, 'request').mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ default_port: 3001, compose_yaml: 'x: 1' }),
  });
}

describe('install window checks (NUX-20)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="os-dock-container"><div id="os-dock"></div></div>';
  });
  afterEach(() => {
    const modal = document.getElementById('app-deploy-modal-overlay');
    if (modal && modal._close) modal._close();
    vi.restoreAllMocks();
  });

  it('says what is wrong with a name or a port, and when all is ready', async () => {
    routes();
    await openAppDeployModal('uptime-kuma');
    const banner = document.getElementById('adm-conflict-banner');
    const name = document.getElementById('adm-name-input');
    const port = document.getElementById('adm-port-input');

    name.value = '';
    name.oninput();
    await wait();
    expect(banner.textContent).toContain('Invalid name: The container needs a name.');

    answers.name = { exists: true, name: 'kuma' };
    name.value = 'kuma';
    name.oninput();
    await wait();
    expect(banner.textContent).toContain('Name in use: A container named kuma already exists.');

    answers.name = { exists: false };
    port.value = '0';
    port.oninput();
    await wait();
    expect(banner.textContent).toContain('Invalid port: Enter a port from 1 to 65535.');

    answers.port = { available: false, in_use_by: 'grafana' };
    port.value = '3001';
    port.oninput();
    await wait();
    expect(banner.textContent).toContain('Port in use: Port 3001 is already in use by grafana.');

    answers.port = { available: true };
    port.oninput();
    await wait();
    expect(banner.textContent).toContain('Ready to install: Port 3001 is free for the container kuma.');
  });

  it('offers to install alongside an existing copy, or to replace it', async () => {
    routes({
      resolve: {
        app_id: 'uptime-kuma',
        default_port: 3001,
        suggested_port: 3002,
        conflict_detected: false,
        existing_container: { name: 'uptime-kuma', state: 'running' },
        suggested_container_name: 'uptime-kuma-2',
      },
    });
    await openAppDeployModal('uptime-kuma');
    const banner = document.getElementById('adm-conflict-banner');
    expect(banner.textContent).toContain('Install alongside:');

    document.getElementById('adm-choice-replace-btn').click();
    await wait(50);
    expect(banner.textContent).toContain('Stop & replace:');

    const name = document.getElementById('adm-name-input');
    answers.name = { exists: true, name: name.value };
    name.oninput();
    await wait();
    expect(banner.textContent).toContain(`The container ${name.value} is stopped and replaced.`);

    answers.port = { available: false, in_use_by: `container '${name.value}'` };
    const port = document.getElementById('adm-port-input');
    port.value = '3001';
    port.oninput();
    await wait();
    expect(banner.textContent).toContain('is used by');
  });

  it('stops an install whose name or port was taken meanwhile, and reports a lost install', async () => {
    routes();
    await openAppDeployModal('uptime-kuma');
    const banner = document.getElementById('adm-conflict-banner');
    const deploy = document.getElementById('adm-deploy-confirm-btn');

    answers.name = { exists: true, name: 'uptime-kuma' };
    await deploy.onclick();
    expect(banner.textContent).toContain('Name in use:');

    answers.name = { exists: false };
    answers.port = { available: false, in_use_by: 'grafana' };
    await deploy.onclick();
    expect(banner.textContent).toContain('Port in use: Port 3001 is already in use by grafana.');

    answers.port = { available: true };
    api.request.mockRejectedValue(new Error(''));
    await deploy.onclick();
    await wait(50);
    expect(DockManager.windows['app-deploy'].title).toBe('❌ UPTIME-KUMA failed to install');
  });
});
