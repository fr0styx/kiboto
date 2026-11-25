import { describe, it, expect } from 'vitest';
import { aboveWindows, installWindowFocus } from '../window-focus.js';

function makeDock() {
  const dock = {
    windows: {},
    register(id, el) {
      this.windows[id] = { el, minimized: false, closed: false };
      el.style.display = 'flex';
    },
    restore() {},
    minimize(id) {
      this.windows[id].minimized = true;
      this.windows[id].el.style.display = 'none';
    },
    unregister(id) {
      this.windows[id].el.style.display = 'none';
      delete this.windows[id];
    },
    closeWindow(id) {
      this.unregister(id);
    },
  };
  installWindowFocus(dock);
  return dock;
}
const frame = () => new Promise((r) => setTimeout(r, 20));
const esc = (el) => el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));

function page(panelZ, winZ) {
  document.body.innerHTML = `
    <div id="notif-center-panel" style="display:flex; z-index:${panelZ}"><button id="nb">n</button></div>
    <div id="w" class="os-window" style="z-index:${winZ}"><div class="os-window-body"><button id="wb">w</button></div></div>`;
}

describe('aboveWindows', () => {
  it('is true only when the panel is drawn above every open window', () => {
    page(1003, 1002);
    expect(aboveWindows(document.getElementById('notif-center-panel'))).toBe(true);
    page(1001, 1002);
    expect(aboveWindows(document.getElementById('notif-center-panel'))).toBe(false);
  });

  it('ignores hidden windows and a hidden panel', () => {
    page(1001, 1002);
    document.getElementById('w').style.display = 'none';
    expect(aboveWindows(document.getElementById('notif-center-panel'))).toBe(true);
    document.getElementById('notif-center-panel').style.display = 'none';
    expect(aboveWindows(document.getElementById('notif-center-panel'))).toBe(false);
  });

  it('reads the z-index of the nearest ancestor that sets one', () => {
    document.body.innerHTML = `
      <div id="notif-center-panel" style="display:flex; z-index:1002"></div>
      <div style="z-index:1005"><div class="mgmt-app-window">settings</div></div>`;
    expect(aboveWindows(document.getElementById('notif-center-panel'))).toBe(false);
  });
});

describe('Esc with the notification centre open', () => {
  it('a window above the notification centre closes, the centre stays', async () => {
    page(1001, 1002);
    const dock = makeDock();
    dock.register('w', document.getElementById('w'));
    await frame();
    document.getElementById('wb').focus();
    esc(document.getElementById('wb'));
    expect(dock.windows.w).toBeUndefined();
    expect(document.getElementById('notif-center-panel').style.display).toBe('flex');
  });

  it('the notification centre on top keeps Esc: the window under it stays open', async () => {
    page(1003, 1002);
    const dock = makeDock();
    dock.register('w', document.getElementById('w'));
    await frame();
    document.getElementById('nb').focus();
    esc(document.getElementById('nb'));
    expect(dock.windows.w).toBeTruthy();
  });
});
