import { describe, it, expect } from 'vitest';
import { whyText, jobsHtml } from '../components/management/protection.js';

describe('the monthly disk check says why once (SET-21, Backup B12)', () => {
  it('no "Off off": the reason is one plain sentence, or nothing on SSD-only pools', () => {
    expect(whyText({ kind: 'scrub', status: 'off', why: "off: a scrub spins up the pool's disks once a month" })).toBe('Turning it on wakes the disks once a month.');
    expect(whyText({ kind: 'scrub', status: 'off', why: 'off' })).toBe('');
    expect(whyText({ kind: 'snapshot', status: 'failed', why: 'failed: no space' })).toBe('failed: no space');
    const html = String(jobsHtml([{ kind: 'scrub', id: 'tank', name: 'tank', status: 'off', why: 'off: a scrub spins up the pool', enabled: false }]));
    expect(html).not.toContain('spins up');
    expect(html).toContain('wakes the disks once a month');
  });
});
