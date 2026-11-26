import { describe, it, expect } from 'vitest';
import markup from '../windows/management-window.html?raw';
import { SUBPANE_MAP, tabForPane } from '../components/management.js';

// the markup is large (about 400 kB): parse it once, the tests only read it
let parsed;
const doc = () => (parsed ??= new DOMParser().parseFromString(markup, 'text/html'));

describe('Storage keeps the drives; Shared folders and Card copies move (SET-22 Storage 2)', () => {
  it('Storage has Drives and Cloud drives, no Shares or Card copies tab', () => {
    const card = /** @type {HTMLElement} */ (doc().getElementById('mgmt-sec-storage'));
    const tabs = [...card.querySelectorAll('.mgmt-inner-tab')]
      .filter((t) => !(/** @type {HTMLElement} */ (t).style.display))
      .map((t) => /** @type {HTMLElement} */ (t).dataset.tabTarget);
    expect(tabs).toEqual(['mgmt-pane-chassis-twin', 'mgmt-pane-storage-remotes']);
    expect(card.querySelector('#mgmt-pane-storage-shares')).toBeNull();
    expect(card.querySelector('#mgmt-pane-copy')).toBeNull();
  });

  it('Shared folders is a section of its own, opened by its sidebar entry and old links', () => {
    const d = doc();
    const sec = /** @type {HTMLElement} */ (d.getElementById('mgmt-sec-shares'));
    expect(sec.querySelector('#mgmt-pane-storage-shares')).not.toBeNull();
    expect(sec.querySelector('.mgmt-inner-tabs')).toBeNull();
    expect(
      /** @type {HTMLElement} */ (d.querySelector('.mgmt-sidebar-item[data-route="shares"]')).dataset.mgmtTarget
    ).toBe('mgmt-sec-shares');
    expect(SUBPANE_MAP['mgmt-pane-storage-shares'].section).toBe('mgmt-sec-shares');
    expect(SUBPANE_MAP['mgmt-sec-shares'].pane).toBe('mgmt-pane-storage-shares');
  });

  it('Card copies sit with the Copy button on Hardware', () => {
    const hw = /** @type {HTMLElement} */ (doc().getElementById('mgmt-sec-hardware'));
    expect(hw.querySelector('#mgmt-pane-copy')).not.toBeNull();
    const tab = tabForPane(hw, 'mgmt-pane-copy');
    // Hardware 2: one page; the one tab shows every section, the copies with the Copy button
    expect(tab?.dataset.tabPanes?.split(' ')).toEqual(
      expect.arrayContaining(['mgmt-pane-hardware-copy', 'mgmt-pane-copy'])
    );
    expect(SUBPANE_MAP['mgmt-pane-copy'].section).toBe('mgmt-sec-hardware');
  });
});
