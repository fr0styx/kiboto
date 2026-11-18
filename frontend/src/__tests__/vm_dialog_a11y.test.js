/** VMs report 35: VM dialogs announce themselves, take focus, close on Escape, ask before discarding. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { asDialog, askBeforeDiscard } from '../components/vm/dialog-a11y.js';

function dlg(id) {
  document.body.innerHTML = `<div id="${id}" class="smart-modal-backdrop" style="display:flex"><div class="smart-modal-window">
    <div class="smart-modal-header"><span class="smart-modal-title">Snapshots</span><button class="win-btn min-btn"></button><button class="win-btn close-btn"></button></div>
    <div class="smart-modal-body"><input id="f1" type="text"></div></div></div>`;
  return /** @type {HTMLElement} */ (document.getElementById(id));
}

describe('VM dialogs and the keyboard (VMs report 35)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('announces a dialog, labels it by its title, focuses the first field, and Escape closes it', () => {
    const b = dlg('modal-vm-snapshots');
    const close = vi.fn();
    b.querySelector('.close-btn')?.addEventListener('click', close);
    const win = asDialog(b);
    expect(win?.getAttribute('role')).toBe('dialog');
    expect(win?.getAttribute('aria-modal')).toBe('true');
    expect(win?.getAttribute('aria-labelledby')).toBe('modal-vm-snapshots-title');
    expect(document.activeElement?.id).toBe('f1');
    b.querySelector('#f1')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(close).toHaveBeenCalledTimes(1);
    b.style.display = 'none';
    b.querySelector('#f1')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(close).toHaveBeenCalledTimes(1);
    expect(asDialog(null)).toBeNull();
  });

  it('Create and Edit: not aria-modal, no own Escape, and a changed form asks before closing', () => {
    const b = dlg('modal-vm-create');
    const win = asDialog(b, { modal: false, escape: false });
    expect(win?.hasAttribute('aria-modal')).toBe(false);
    const close = vi.fn();
    expect(askBeforeDiscard(b, close)).toBe(false);
    expect(close).toHaveBeenCalledTimes(1);
    b.querySelector('#f1')?.dispatchEvent(new Event('input', { bubbles: true }));
    expect(askBeforeDiscard(b, close)).toBe(true);
    expect(close).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).toContain('Close without saving? Your changes are lost.');
    asDialog(b, { modal: false, escape: false }); // opening again starts clean
    expect(b.dataset.dirty).toBe('');
  });
});
