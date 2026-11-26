// The app's cards read the feature table: the same words as GitHub and the website.
import { describe, it, expect } from 'vitest';
import { editionLine } from '../edition-line.js';

describe('the line a card shows for this edition', () => {
  it('names what the feature table says, and nothing where it simply works', () => {
    expect(editionLine('check')).toBe('Built for this edition, and still being checked.');
    expect(editionLine('host')).toBe('Your NAS system does this here.');
    expect(editionLine('no')).toBe('Not offered on this edition.');
    expect(editionLine('soon')).toBe('Not on this edition yet.');
    for (const plain of ['yes', 'partly', 'view', '', undefined]) expect(editionLine(plain)).toBe('');
  });
});
