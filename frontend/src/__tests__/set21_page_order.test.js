import { describe, it, expect } from 'vitest';
import markup from '../windows/management-window.html?raw';

describe("Backup in the report's order (SET-21 stage 4)", () => {
  it('safe?, get back, copies outside, earlier versions, phones and computers, then More folded', () => {
    const doc = new DOMParser().parseFromString(markup, 'text/html');
    const pane = /** @type {HTMLElement} */ (doc.getElementById('mgmt-pane-backups'));
    const ids = ['backup-verdict', 'backup-restore', 'offsite-backup-mount', 'backup-fleet-grid', 'snapshot-schedules-mount', 'phone-backup-mount', 'backup-jobs-mount', 'protection-jobs-mount'];
    const at = ids.map((id) => [...pane.querySelectorAll('[id]')].findIndex((e) => e.id === id));
    expect(at.every((n) => n >= 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    const more = /** @type {HTMLDetailsElement} */ (pane.querySelector('details.bk-more'));
    expect(more.open).toBe(false);
    for (const id of ['backup-jobs-mount', 'app-backups-mount', 'two-way-sync-mount', 'protection-jobs-mount', 'btn-backup-download']) expect(more.querySelector(`#${id}`)).not.toBeNull();
    expect(pane.querySelector('[data-i18n="mgmt.backups_title"]')).toBeNull();
    for (const id of ['btn-refresh-backup-jobs', 'btn-refresh-snapshots', 'btn-refresh-app-backups']) expect(doc.getElementById(id)).toBeNull();
    expect(/** @type {HTMLDetailsElement} */ (pane.querySelector('details.bk-all-versions')).querySelector('#system-snapshots-mount')).not.toBeNull();
  });
});
