/** A pool that is not there has its own word and reads as a problem, not as healthy. */
import { describe, it, expect } from 'vitest';
import { poolStatusWord } from '../components/chassis-visualizer.js';
import { setLanguage } from '../i18n.js';

describe('pool status words', () => {
  it('names a missing pool', async () => {
    await setLanguage('en');
    expect(poolStatusWord('MISSING')).toBe('Not found');
    expect(poolStatusWord('HEALTHY')).toBe('Healthy');
    await setLanguage('de');
    expect(poolStatusWord('MISSING')).toBe('Nicht gefunden');
    await setLanguage('en');
  });
});
