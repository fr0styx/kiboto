import { describe, it, expect } from 'vitest';
import markup from '../windows/management-window.html?raw';

describe('Shared folders: the name, the folders first, the rest folded (SET-22, Shares 5)', () => {
  it('is called Shared folders; the protocol state and SFTP sit folded at the end', () => {
    const doc = new DOMParser().parseFromString(markup, 'text/html');
    const pane = /** @type {HTMLElement} */ (doc.getElementById('mgmt-pane-storage-shares'));
    expect(pane.querySelector('[data-i18n="shares.page_title"]')?.textContent).toBe('Shared folders');
    expect(doc.getElementById('btn-refresh-shares')).toBeNull();
    const adv = /** @type {HTMLDetailsElement} */ (pane.querySelector('details#shares-advanced'));
    expect(adv.open).toBe(false);
    expect(adv.querySelector('#proto-pill-smb')).not.toBeNull();
    expect(adv.querySelector('#shares-sftp-mount')).not.toBeNull();
    const ids = [...pane.querySelectorAll('[id]')].map((e) => e.id);
    expect(ids.indexOf('mgmt-storage-shares-mount')).toBeLessThan(ids.indexOf('shares-advanced'));
  });
});
