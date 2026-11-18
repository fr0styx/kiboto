import { describe, it, expect } from 'vitest';
import { MAIN_ROLES, MORE_ROLES } from '../components/add-person.js';

describe('each role says what it can reach (SET-19, Users A12)', () => {
  it("names private folders, app data and other people's files where a role reaches them", () => {
    const line = Object.fromEntries([...MAIN_ROLES(), ...MORE_ROLES()].map(([id, , d]) => [id, d]));
    expect(line.superadmin).toContain('every private folder');
    expect(line.storage_admin).toContain('every private folder');
    expect(line.app_operator).toContain('most data folders');
    expect(line.backup_operator).toContain("anyone's files");
  });
});
