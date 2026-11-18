import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { syncBackupJobForm } from '../components/management/system.js';

const html = fs.readFileSync(path.resolve(__dirname, '../windows/management-window.html'), 'utf8');

describe('the job dialog backs up the settings only (SET-21 stage 3, decision 2 A)', () => {
  it('offers no folder kind; the settings fields show from the first look', () => {
    document.body.innerHTML = html;
    const kind = /** @type {HTMLSelectElement} */ (document.getElementById('backup-job-kind'));
    expect([...kind.options].map((o) => o.value)).toEqual(['config']);
    expect(kind.hidden).toBe(true);
    syncBackupJobForm();
    expect(/** @type {HTMLElement} */ (document.getElementById('backup-config-fields')).hidden).toBe(false);
    expect(/** @type {HTMLSelectElement} */ (document.getElementById('backup-job-dest-type')).value).toBe(
      'local_folder'
    );
    expect(document.getElementById('btn-open-create-backup-job')?.textContent).toContain(
      'Back up the settings on a schedule'
    );
  });
});
