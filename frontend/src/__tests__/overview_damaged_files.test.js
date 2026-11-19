// Re-audit R6: the Overview names the damaged files a check found.
import { describe, it, expect } from 'vitest';
import { itemText } from '../components/management/overview.js';

describe('Overview: damaged files', () => {
  it('says the pool, how many and the first names, and what to do', () => {
    const text = itemText({ kind: 'damaged_files', subject: 'tank', detail: '5', files: 'a.jpg, b.jpg, c.pdf (+2)' });
    expect(text).toBe('Damaged files in tank (5): a.jpg, b.jpg, c.pdf (+2). Restore them from a backup or a snapshot.');
  });

  it('other lines are unchanged when an item carries no file names', () => {
    expect(itemText({ kind: 'scrub_errors', subject: 'tank', detail: '3' })).toBe(
      'The last check of tank found errors in the data.'
    );
    expect(itemText({ kind: 'damaged_files', subject: 'tank', detail: '1' })).toContain('Damaged files in tank (1): .');
  });
});
