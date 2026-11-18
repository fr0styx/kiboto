import { describe, it, expect } from 'vitest';
import markup from '../windows/management-window.html?raw';
import { SUBPANE_MAP } from '../components/management.js';
import { ADVANCED_ROUTES, ADVANCED_SECTIONS } from '../advanced.js';
import { applyAdvanced } from '../components/management/overview.js';

const doc = () => new DOMParser().parseFromString(markup, 'text/html');

describe('Activity opens on History; Right now is for Advanced (SET-27 Activity 2)', () => {
  it("the event log is Activity's first tab, and left Settings", () => {
    const d = doc();
    const act = /** @type {HTMLElement} */ (d.getElementById('mgmt-sec-activity'));
    const tabs = [...act.querySelectorAll('.mgmt-inner-tab')].map(
      (t) => /** @type {HTMLElement} */ (t).dataset.tabTarget
    );
    expect(tabs).toEqual(['mgmt-pane-events', 'mgmt-pane-metrics']);
    expect(act.querySelector('#mgmt-pane-events #events-list')).not.toBeNull();
    expect(d.getElementById('mgmt-sec-system-group')?.querySelector('[data-tab-target="mgmt-pane-events"]')).toBeNull();
    expect(act.querySelector('#mgmt-tab-now')?.hasAttribute('data-advanced-tab')).toBe(true);
  });

  it('links open History; Activity is no longer an Advanced page', () => {
    expect(SUBPANE_MAP['mgmt-sec-activity']).toEqual({ section: 'mgmt-sec-activity', pane: 'mgmt-pane-events' });
    expect(SUBPANE_MAP['mgmt-pane-events'].section).toBe('mgmt-sec-activity');
    expect(SUBPANE_MAP['mgmt-pane-metrics'].pane).toBe('mgmt-pane-metrics');
    expect(ADVANCED_ROUTES).not.toContain('activity');
    expect(ADVANCED_SECTIONS).not.toContain('mgmt-sec-activity');
  });

  it('Right now hides with Advanced off and comes back with it on', () => {
    document.body.innerHTML = '<button id="now" data-advanced-tab></button>';
    const now = /** @type {HTMLElement} */ (document.getElementById('now'));
    applyAdvanced(false);
    expect(now.hidden).toBe(true);
    applyAdvanced(true);
    expect(now.hidden).toBe(false);
  });
});
