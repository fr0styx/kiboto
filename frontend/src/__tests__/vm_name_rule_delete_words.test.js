/** VMs report 24-25: the name rule is said before the server refuses, and delete says what is erased. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const src = (p) => readFileSync(resolve(__dirname, '..', p), 'utf8');

describe('VM names and delete (VMs report 24-25)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('the create form shows the rule the server enforces', () => {
    const create = src('components/vm/create-modal.js');
    expect(create).toContain('id="vm-create-name-rule"');
    expect(create).toContain("/^[a-zA-Z0-9_-]{2,64}$/");
    const server = readFileSync(resolve(__dirname, '../../../backend/api/vms.py'), 'utf8');
    expect(server).toContain('min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$"');
    expect(server).toContain('SNAPSHOT_NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"');
    expect(src('components/vm/snapshots.js')).toContain("/^[a-zA-Z0-9_-]{1,64}$/");
  });

  it('delete says the disks and snapshots are erased and backups kept', () => {
    expect(src('locales/en.js')).toContain('"vm.delete_erases": "Delete {name}? Its disks and snapshots are erased. Backups are kept."');
    expect(src('components/vm-manager.js')).toContain("t('vm.delete_erases'");
    expect(src('components/vm-manager.js')).not.toContain('Are you sure you want to delete virtual machine');
  });
});
