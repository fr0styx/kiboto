// The npm vulnerability gate and its one kind of exception (17 Nov, owner's decision).
import { describe, it, expect } from 'vitest';
import { problems, newer, advisoryId, EXCEPTIONS } from '../../scripts/npm-audit-gate.mjs';

const PICO = { source: 1, name: 'picomatch', severity: 'high', url: 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf', range: '*' };
// the shape npm audit --json reported on 17 Nov: picomatch through fdir, tinyglobby, vite, vitest and coverage (a cycle)
const AUDIT = {
  vulnerabilities: {
    picomatch: { severity: 'high', via: [PICO] },
    fdir: { severity: 'high', via: ['picomatch'] },
    tinyglobby: { severity: 'high', via: ['fdir', 'picomatch'] },
    vite: { severity: 'high', via: ['picomatch', 'tinyglobby'] },
    vitest: { severity: 'high', via: ['@vitest/coverage-v8', 'picomatch', 'tinyglobby', 'vite'] },
    '@vitest/coverage-v8': { severity: 'high', via: ['vitest'] },
  },
};
const LATEST = { picomatch: '4.0.7' };

describe('npm audit gate', () => {
  it('lets the named advisory through when it reaches build tools only', () => {
    expect(problems(AUDIT, new Set(['chart.js', 'dompurify']), LATEST)).toEqual([]);
  });

  it('fails again once a fixed version is published', () => {
    const out = problems(AUDIT, new Set(), { picomatch: '4.0.8' });
    expect(out[0]).toContain('4.0.8 is out');
    expect(out.length).toBeGreaterThan(1); // and the advisory counts again
  });

  it('fails when an excused package ships', () => {
    expect(problems(AUDIT, new Set(['picomatch']), LATEST)).toEqual([expect.stringContaining('picomatch: excused advisory but it ships')]);
  });

  it('fails on any other high or critical advisory, even through an excused package', () => {
    const other = { url: 'https://github.com/advisories/GHSA-zzzz-zzzz-zzzz', severity: 'critical' };
    const audit = { vulnerabilities: { ...AUDIT.vulnerabilities, vite: { severity: 'critical', via: ['picomatch', other] }, lodash: { severity: 'high', via: [other] } } };
    const out = problems(audit, new Set(), LATEST);
    expect(out.some((l) => l.startsWith('vite: critical'))).toBe(true);
    expect(out.some((l) => l.startsWith('vitest: high'))).toBe(true); // reaches vite's other advisory
    expect(out.some((l) => l.startsWith('lodash: high'))).toBe(true);
  });

  it('moderate advisories and an empty report pass', () => {
    expect(problems({ vulnerabilities: { x: { severity: 'moderate', via: [{ url: 'https://x/GHSA-a' }] } } }, new Set(), LATEST)).toEqual([]);
    expect(problems({}, new Set(), {})).toEqual([]);
  });

  it('helpers', () => {
    expect(newer('4.0.10', '4.0.7')).toBe(true);
    expect(newer('4.0.7', '4.0.7')).toBe(false);
    expect(newer('4.1', '4.0.7')).toBe(true);
    expect(newer('3.9.9', '4.0.7')).toBe(false);
    expect(advisoryId(PICO)).toBe('GHSA-fc5q-39xc-vjpf');
    expect(advisoryId({})).toBe('');
    expect(Object.keys(EXCEPTIONS)).toEqual(['GHSA-fc5q-39xc-vjpf']);
  });
});
