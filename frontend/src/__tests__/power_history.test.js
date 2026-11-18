// SET-31, Power stage 3: power history in sentences, the last five first.
import { describe, it, expect } from 'vitest';
import { lasted, historySentence, renderPowerHistory, FIRST_ROWS } from '../components/management/power-history.js';

describe('power history', () => {
  it('says how long, in words', () => {
    expect(lasted(1)).toBe('1 second');
    expect(lasted(45)).toBe('45 seconds');
    expect(lasted(600)).toBe('10 minutes');
    expect(lasted(7200)).toBe('2 hours');
    expect(lasted(null)).toBe('0 seconds');
  });

  it('says each event as a sentence', () => {
    expect(
      historySentence({
        event_type: 'OUTAGE_RECOVERED',
        duration_sec: 120,
        start_battery_pct: 100,
        end_battery_pct: 85.4,
      })
    ).toBe('The power was out for 2 minutes. The battery went from 100 % to 85 %.');
    expect(historySentence({ event_type: 'OUTAGE_RECOVERED', duration_sec: 30 })).toBe(
      'The power was out for 30 seconds.'
    );
    expect(historySentence({ event_type: 'FAILSAFE_SHUTDOWN', end_battery_pct: 9 })).toBe(
      'The battery ran low (9 % left), and the NAS was shut down safely.'
    );
    expect(historySentence({ event_type: 'FAILSAFE_SHUTDOWN' })).toBe(
      'The battery ran low, and the NAS was shut down safely.'
    );
    expect(historySentence({ event_type: 'SELF_TEST' })).toBe('A battery test was sent to the UPS.');
    expect(historySentence({ event_type: 'OUTAGE_SIMULATION' })).toMatch(/^Practice run/);
    expect(historySentence({ event_type: 'SOMETHING', action_taken: 'Done.' })).toBe('Done.');
    expect(historySentence(null)).toBe('');
  });

  it('shows five, and the rest after "Show all"', () => {
    document.body.innerHTML = '<div id="h"></div>';
    const mount = /** @type {HTMLElement} */ (document.getElementById('h'));
    const events = Array.from({ length: 8 }, (_, i) => ({ ts: 1762900000 - i * 3600, event_type: 'SELF_TEST' }));
    renderPowerHistory(mount, events);
    expect(mount.querySelectorAll('li')).toHaveLength(FIRST_ROWS);
    const more = /** @type {HTMLElement} */ (mount.querySelector('.pwh-more'));
    expect(more.textContent).toBe('Show all (8)');
    more.click();
    expect(mount.querySelectorAll('li')).toHaveLength(8);
    expect(mount.querySelector('.pwh-more')).toBeNull();
    renderPowerHistory(mount, []);
    expect(mount.textContent).toBe('No power cuts recorded yet.');
    renderPowerHistory(null, events); // no place: nothing happens
  });
});
