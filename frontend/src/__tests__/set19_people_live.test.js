import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { installPeopleLive, peopleShown } from '../components/people-live.js';

function bus() {
  const handlers = [];
  return { on: (name, fn) => handlers.push([name, fn]), emit: (s) => handlers.forEach(([, fn]) => fn(s)), handlers };
}

describe('the People lists update themselves (SET-19)', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('reloads once a little after the count moves, only while People is shown', () => {
    const b = bus();
    const reload = vi.fn();
    let shown = true;
    installPeopleLive({ bus: b, reload, shown: () => shown, settleMs: 100 });
    expect(b.handlers[0][0]).toBe('stats:updated');
    b.emit({ security: { people_rev: 3 } }); // the first count only sets the mark
    vi.advanceTimersByTime(200);
    expect(reload).not.toHaveBeenCalled();
    b.emit({ security: { people_rev: 4 } });
    b.emit({ security: { people_rev: 5 } }); // two changes, one reload
    vi.advanceTimersByTime(200);
    expect(reload).toHaveBeenCalledTimes(1);
    shown = false;
    b.emit({ security: { people_rev: 6 } });
    vi.advanceTimersByTime(200);
    expect(reload).toHaveBeenCalledTimes(1);
    b.emit({ cpu: 3 }); // stats without the count change nothing
    b.emit(null);
    shown = true;
    b.emit({ security: { people_rev: 6 } }); // same count: nothing to reload
    vi.advanceTimersByTime(200);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('knows when People is on screen', () => {
    document.body.innerHTML =
      '<div id="management-modal-overlay" style="display:block"><div id="mgmt-pane-users" style="display:block"></div></div>';
    expect(peopleShown()).toBe(true);
    /** @type {HTMLElement} */ (document.getElementById('mgmt-pane-users')).style.display = 'none';
    expect(peopleShown()).toBe(false);
    /** @type {HTMLElement} */ (document.getElementById('mgmt-pane-users')).style.display = 'block';
    /** @type {HTMLElement} */ (document.getElementById('management-modal-overlay')).style.display = 'none';
    expect(peopleShown()).toBe(false);
    document.body.innerHTML = '';
    expect(peopleShown()).toBe(false);
  });
});
