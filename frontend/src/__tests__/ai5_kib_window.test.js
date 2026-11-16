/** AI 5 (decision 1): Ask and Search are the Kib window; Settings → Kib is the settings. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

vi.mock('../management-dom.js', () => ({ ensureManagementDom: vi.fn(async () => {}), onManagementDom: (fn) => fn(), isManagementDomReady: () => true }));
vi.mock('../components/management/ai.js', () => ({ fetchAndRenderAiStatus: vi.fn(), runAiVisualSearch: vi.fn(), _getActiveAiSearchQuery: vi.fn(() => '') }));
vi.mock('../components/management/kib-access.js', () => ({ loadKibExtras: vi.fn() }));

const { openKibWindow, kibPane, isKibWindowPane, ensureKibWindow, adoptPanes, showKibPane, KIB_PANES } = await import('../components/kib-window.js');
const ai = await import('../components/management/ai.js');
const access = await import('../components/management/kib-access.js');
const flush = () => new Promise((r) => setTimeout(r, 0));

const SETTINGS = `<div id="mgmt-sec-ai">
  <button id="mgmt-tab-ai-chat"></button><button id="mgmt-tab-ai-rag"></button><button id="mgmt-tab-ai-index"></button>
  <div id="mgmt-pane-ai-chat" class="mgmt-tab-pane"><textarea id="ai-chat-input"></textarea></div>
  <div id="mgmt-pane-ai-rag" class="mgmt-tab-pane"></div>
  <div id="mgmt-pane-ai-index" class="mgmt-tab-pane"></div></div>`;

describe('Kib window (AI 5)', () => {
  beforeEach(() => {
    document.body.innerHTML = SETTINGS;
    vi.clearAllMocks();
    window.DockManager = { windows: {}, register: vi.fn(function (id) { this.windows[id] = {}; }), restore: vi.fn(), minimize: vi.fn(), closeWindow: vi.fn() };
  });
  afterEach(() => { delete window.DockManager; });

  it('maps links to the window\'s two panes', () => {
    expect(kibPane('mgmt-pane-ai-visual')).toBe('mgmt-pane-ai-rag');
    expect(kibPane('mgmt-pane-ai-rag')).toBe('mgmt-pane-ai-rag');
    expect(kibPane(undefined)).toBe('mgmt-pane-ai-chat');
    expect(['mgmt-pane-ai-chat', 'mgmt-pane-ai-rag', 'mgmt-pane-ai-visual', 'mgmt-pane-ai-index'].map(isKibWindowPane)).toEqual([true, true, true, false]);
    expect(KIB_PANES).toEqual(['mgmt-pane-ai-chat', 'mgmt-pane-ai-rag']);
  });

  it('opens on Ask, takes the panes out of Settings and hides their tabs there', async () => {
    const win = await openKibWindow();
    expect(win.id).toBe('kib-window');
    expect(win.querySelector('.kib-window-body').children).toHaveLength(2);
    expect(document.getElementById('mgmt-sec-ai').querySelector('#mgmt-pane-ai-chat')).toBeNull();
    expect(document.getElementById('mgmt-pane-ai-index').closest('#mgmt-sec-ai')).not.toBeNull();
    expect(document.getElementById('mgmt-tab-ai-chat').hidden).toBe(true);
    expect(document.getElementById('mgmt-tab-ai-rag').hidden).toBe(true);
    expect(document.getElementById('mgmt-pane-ai-chat').style.display).toBe('flex');
    expect(document.getElementById('mgmt-pane-ai-rag').style.display).toBe('none');
    expect(window.DockManager.register).toHaveBeenCalledWith('kib', win, '#i-kib', 'Kib');
    await flush(); await flush();
    expect(ai.fetchAndRenderAiStatus).toHaveBeenCalled();
    expect(document.activeElement.id).toBe('ai-chat-input');
    await openKibWindow('mgmt-pane-ai-visual'); // a second open reuses the window
    expect(document.querySelectorAll('#kib-window')).toHaveLength(1);
    expect(window.DockManager.register).toHaveBeenCalledTimes(1);
    expect(document.getElementById('mgmt-pane-ai-rag').style.display).toBe('block');
    await flush(); await flush();
    expect(ai.runAiVisualSearch).toHaveBeenCalled();
    expect(access.loadKibExtras).toHaveBeenCalledWith('mgmt-pane-ai-rag');
  });

  it('its tabs switch panes, and its buttons minimise, close and maximise', async () => {
    const win = await openKibWindow('mgmt-pane-ai-chat');
    win.querySelector('[data-kib-tab="mgmt-pane-ai-rag"]').click();
    expect(win.querySelector('[data-kib-tab="mgmt-pane-ai-rag"]').getAttribute('aria-selected')).toBe('true');
    win.querySelector('[data-kibw="max"]').click();
    expect(win.classList.contains('is-maximized')).toBe(true);
    win.querySelector('[data-kibw="min"]').click();
    expect(window.DockManager.minimize).toHaveBeenCalledWith('kib');
    expect(win.style.display).toBe('none');
    win.querySelector('[data-kibw="close"]').click();
    expect(window.DockManager.closeWindow).toHaveBeenCalledWith('kib');
    delete window.DockManager;
    win.querySelector('[data-kibw="close"]').click(); // without a dock it still hides
    await openKibWindow('mgmt-pane-ai-chat');
    expect(win.style.display).toBe('flex');
  });

  it('copes with a page that has no panes', () => {
    document.body.innerHTML = '';
    const win = ensureKibWindow();
    adoptPanes(win);
    showKibPane('mgmt-pane-ai-chat');
    adoptPanes(document.createElement('div'));
    expect(win.querySelector('.kib-window-body').children).toHaveLength(0);
  });

  it('Settings → Kib opens on its settings, with a way to the window', () => {
    const html = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');
    expect(html).toMatch(/id="mgmt-tab-ai-chat" hidden/);
    expect(html).toMatch(/id="mgmt-tab-ai-rag" hidden/);
    expect(html).toMatch(/class="mgmt-inner-tab active"[^>]*id="mgmt-tab-ai-index"/);
    expect(html).toContain('data-kib-open');
    const mgmt = fs.readFileSync(path.resolve(__dirname, '../components/management.js'), 'utf8');
    expect(mgmt).toContain("'ai': { section: 'mgmt-sec-ai', pane: 'mgmt-pane-ai-index' }");
    expect(fs.readFileSync(path.resolve(__dirname, '../main.js'), 'utf8')).toContain("'openKibWindow'");
  });
});
