import { describe, it, expect } from 'vitest';
import markup from '../windows/management-window.html?raw';

describe("General in the report's order (SET-23, Settings 3)", () => {
  it('Software update first, then This server with the details folded, then the report for support', () => {
    const doc = new DOMParser().parseFromString(markup, 'text/html');
    const pane = /** @type {HTMLElement} */ (doc.getElementById('mgmt-pane-about'));
    const ids = [...pane.querySelectorAll('[id]')].map((e) => e.id);
    expect(ids.indexOf('about-version-badge')).toBeGreaterThan(ids.findIndex((id) => /update/i.test(id)));
    const tech = /** @type {HTMLDetailsElement} */ (pane.querySelector('details.ab-tech'));
    expect(tech.open).toBe(false);
    expect(tech.querySelector('#about-chassis-model')).not.toBeNull();
    expect(pane.querySelector('[data-i18n="mw.all_in_one_nas_hardware_and"]')).toBeNull();
    expect(pane.textContent.indexOf('Diagnostics')).toBeGreaterThan(pane.textContent.indexOf('Technical details'));
  });
});
