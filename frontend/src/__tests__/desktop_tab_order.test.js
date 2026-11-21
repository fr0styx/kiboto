/** While a window is open, Tab leaves the desktop behind it out; clicks are not touched. */
import { describe, it, expect, beforeEach } from 'vitest';
import { anyWindowShown, syncDesktopTabOrder } from '../components/dock/desktop-tab-order.js';

const tick = () => new Promise((done) => setTimeout(done, 0));

describe('the desktop and the Tab key', () => {
  let win;
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="desktop-icons-container"><div id="a-icon" tabindex="0">A</div><div id="b-icon" tabindex="2">B</div></div>
      <div id="desktop-widgets-container"><button id="w-btn">Refresh</button><span>clock</span></div>
      <div class="getting-started-card"><a id="gs-link" href="#">Open</a></div>
      <div id="win" class="os-window" style="display:flex"><button id="in-win">OK</button></div>`;
    win = document.getElementById('win');
    syncDesktopTabOrder({});
  });

  it('knows when a window shows', () => {
    expect(anyWindowShown({})).toBe(false);
    expect(anyWindowShown({ fm: { el: win, minimized: false, closed: false } })).toBe(true);
    expect(anyWindowShown({ fm: { el: win, minimized: true, closed: false } })).toBe(false);
    win.style.display = 'none';
    expect(anyWindowShown({ fm: { el: win, minimized: false, closed: false } })).toBe(false);
  });

  it('leaves the desktop out while a window is open and gives each element its own tab stop back', async () => {
    syncDesktopTabOrder({ fm: { el: win, minimized: false, closed: false } });
    for (const id of ['a-icon', 'b-icon', 'w-btn', 'gs-link']) {
      expect(document.getElementById(id).getAttribute('tabindex')).toBe('-1');
    }
    expect(document.getElementById('in-win').hasAttribute('tabindex')).toBe(false); // the window is untouched
    // a widget that redraws while the window is open stays out
    document
      .getElementById('desktop-widgets-container')
      .insertAdjacentHTML('beforeend', '<button id="w-new">New</button>');
    await tick();
    expect(document.getElementById('w-new').getAttribute('tabindex')).toBe('-1');

    syncDesktopTabOrder({ fm: { el: win, minimized: true, closed: false } });
    expect(document.getElementById('a-icon').getAttribute('tabindex')).toBe('0');
    expect(document.getElementById('b-icon').getAttribute('tabindex')).toBe('2');
    expect(document.getElementById('w-btn').hasAttribute('tabindex')).toBe(false);
    expect(document.getElementById('w-new').hasAttribute('tabindex')).toBe(false);
    expect(document.querySelectorAll('[data-kb-tab]').length).toBe(0);
  });

  it('a second look while a window stays open keeps the elements own values', () => {
    const open = { fm: { el: win, minimized: false, closed: false } };
    syncDesktopTabOrder(open);
    syncDesktopTabOrder(open);
    syncDesktopTabOrder({});
    expect(document.getElementById('b-icon').getAttribute('tabindex')).toBe('2');
  });
});
