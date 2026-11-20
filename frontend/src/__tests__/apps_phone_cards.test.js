/** Apps on a phone: a short card for each app. What the card no longer shows is in its menu. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import fs from 'fs';
import path from 'path';
import {
  initContainersManager,
  renderContainersWindowTable,
  runItems,
  stopCwAutoRefresh,
  _resetCwAutoRefreshForTesting,
  _setCwUpdatesCacheForTesting,
} from '../components/containers-manager.js';
import { DockManager } from '../components/dock.js';
import { api } from '../api.js';
import { showBottomSheet } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const css = fs.readFileSync(path.resolve(__dirname, '../styles/containers-lazy.css'), 'utf8');
const phone = css.slice(css.indexOf('/* Apps on a phone: one short card for each app'));
const labels = (items) => items.map((i) => i.label);

/** A row's button group as the table draws it: the menu button and the buttons it presses. */
function group(...actions) {
  const wrap = document.createElement('div');
  for (const action of [...actions, 'more-sheet']) {
    const b = document.createElement('button');
    b.dataset.action = action;
    wrap.append(b);
  }
  return /** @type {HTMLElement} */ (wrap.lastElementChild);
}

describe('what starts and stops an app, as menu items', () => {
  it('a running app can be restarted and stopped, a stopped one started, a paused one resumed', () => {
    const more = group('restart', 'stop', 'start', 'unpause');
    expect(labels(runItems({ state: 'running', condition: 'running' }, more))).toEqual(['Restart', 'Stop']);
    expect(labels(runItems({ state: 'exited', condition: 'stopped' }, more))).toEqual(['Start']);
    const paused = runItems({ state: 'paused', condition: 'paused' }, more);
    expect(labels(paused)).toEqual(['Resume', 'Restart', 'Stop']);
    expect(paused[0].icon).toBe('▶'); // a sign the icon set draws: "⏵" was an empty box
  });

  it('an item presses the button of its own row', () => {
    const more = group('restart', 'stop');
    const pressed = [];
    for (const b of more.parentElement.querySelectorAll('button'))
      b.addEventListener('click', () => pressed.push(b.dataset.action));
    const [restart, stop] = runItems({ state: 'running', condition: 'running' }, more);
    restart.onClick();
    stop.onClick();
    expect(pressed).toEqual(['restart', 'stop']);
  });

  it('a row that was drawn again in the meantime is not pressed, and nothing breaks', () => {
    const gone = document.createElement('button'); // no longer in a row
    const bare = group(); // a row without that button
    for (const more of [gone, bare])
      for (const item of runItems({ state: 'exited', condition: 'stopped' }, more))
        expect(item.onClick()).toBeUndefined();
  });
});

describe('the Apps window, for a phone', () => {
  beforeEach(() => {
    localStorage.setItem('kiboto_apps_details', '1');
    document.body.innerHTML = '<div id="os-dock-container"><div id="os-dock"></div></div>';
    window._containersManagerInitialized = false;
    window.DockManager = DockManager;
    DockManager.windows = {};
    _resetCwAutoRefreshForTesting();
    vi.clearAllMocks();
    vi.spyOn(api, 'get').mockResolvedValue([]);
    vi.spyOn(api, 'post').mockResolvedValue({});
  });
  afterEach(() => {
    stopCwAutoRefresh();
    _resetCwAutoRefreshForTesting();
    _setCwUpdatesCacheForTesting(null);
    vi.restoreAllMocks();
    localStorage.removeItem('kiboto_apps_details');
  });

  it('with the Docker details, the menu of an app starts with restart and stop', () => {
    initContainersManager();
    renderContainersWindowTable([
      { id: 'c1', name: 'web', image: 'nginx', state: 'running' },
      { id: 'c2', name: 'bare', image: 'nginx', state: 'exited' },
    ]);
    const more = (id) =>
      /** @type {HTMLElement} */ (
        document.querySelector(`#cw-docker-containers-tbody [data-action="more-sheet"][data-id="${id}"]`)
      );
    more('c1').click();
    const running = showBottomSheet.mock.calls.at(-1)[0].items;
    expect(labels(running).slice(0, 4)).toEqual(['Restart', 'Stop', 'Details', 'Show the log']);
    const stop = vi.fn();
    more('c1').parentElement.querySelector('[data-action="stop"]').addEventListener('click', stop);
    running[1].onClick();
    expect(stop).toHaveBeenCalledTimes(1);
    more('c2').click();
    expect(labels(showBottomSheet.mock.calls.at(-1)[0].items)[0]).toBe('Start');
  });

  it('the details switch stands beside the buttons, not among them', () => {
    initContainersManager();
    const win = document.getElementById('containers-manager-window');
    expect(win.querySelector('.cwm-row > .cw-details-switch #cw-details-toggle')).not.toBeNull();
    expect(win.querySelector('.cw-action-btns-wrap .cw-details-switch')).toBeNull();
    // a desktop keeps it at the right end of the buttons
    expect(css).toContain('#containers-manager-window .cwm-row > .cw-action-btns-wrap { margin-left: auto; }');
  });

  it('a card is a grid: name over state, the buttons beside both, the details on a third line', () => {
    expect(phone).toMatch(/@media \(max-width: 768px\) \{/);
    const at = (cell) =>
      (phone.match(new RegExp(`tbody td\\.${cell} \\{ grid-area: ([0-9 /]+);`)) || [])[1]?.replace(/\s/g, '');
    expect(at('docker-name-cell')).toBe('1/1/2/5');
    expect(at('docker-status-cell')).toBe('2/1/3/5');
    expect(at('docker-open-cell')).toBe('1/5/3/6');
    expect(at('docker-actions-cell')).toBe('1/6/3/7');
    for (const cell of ['docker-stack-cell', 'docker-hw-cell', 'docker-telemetry-cell'])
      expect(at(cell)).toMatch(/^3\//);
    expect(at('docker-ports-cell')).toBe('3/4/4/7');
  });

  it('a card shows one button for what the app can do now, and the menu', () => {
    expect(phone).toContain(
      '.docker-actions-btn-group > .btn-container-act:not(.btn-docker-more-sheet, .btn-docker-start, .btn-docker-resume) { display: none !important; }'
    );
    expect(phone).toContain('.docker-name-cell code { display: none; }'); // the id is under Details
  });

  it('above the list, the counts are left to the filter buttons, and nothing to list stands in the middle', () => {
    expect(phone).toContain('.cwm-row-xs-muted { display: none !important; }');
    expect(phone).toMatch(
      /> td\[colspan\] \{ display: block !important; width: 100% !important;[^}]*text-align: center !important; \}/
    );
  });
});
