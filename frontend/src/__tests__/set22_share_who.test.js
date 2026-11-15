import { describe, it, expect, vi } from 'vitest';

const get = vi.fn();
vi.mock('../api.js', () => ({ api: { get } }));
const sw = await import('../components/share-who.js');
const P = (name, level) => ({ username: name.toLowerCase(), name, level });

describe('who can open it (SET-22, Shares 2)', () => {
  it('one sentence: who can change, who can view; many become a count', () => {
    expect(sw.whoSentence([P('Anna', 'write'), P('Ben', 'write'), P('Mia', 'read'), P('Leo', 'none')], '', 'en')).toBe('Anna and Ben can change it. Mia can view it.');
    expect(sw.whoSentence(['A', 'B', 'C', 'D'].map((n) => P(n, 'write')), '', 'en')).toBe('4 people can change it.');
    expect(sw.whoSentence([P('Leo', 'none')], '', 'en')).toBe('Nobody can open it yet.');
    expect(sw.whoSentence([P('Anna', 'write')], 'Unraid', 'en')).toBe('In Files: Anna can change it. Over the network: Unraid decides.');
  });

  it('puts the sentence on each card; a refusal adds nothing', async () => {
    document.body.innerHTML = '<div id="g"><div data-share="photos"><div class="share-card-header"></div></div><div data-share="media"><div class="share-card-header"></div></div></div>';
    const grid = /** @type {HTMLElement} */ (document.getElementById('g'));
    get.mockResolvedValueOnce({ host: 'unraid', shares: [{ name: 'photos', people: [P('Anna', 'write')] }] });
    await sw.fillWhoLines(grid, { unraid: 'Unraid' });
    expect(grid.querySelector('[data-share="photos"] .share-who')?.textContent).toBe('In Files: Anna can change it. Over the network: Unraid decides.');
    expect(grid.querySelector('[data-share="media"] .share-who')).toBeNull();
    get.mockRejectedValueOnce(new Error('403'));
    expect(await sw.fillWhoLines(grid)).toBeNull();
    expect(await sw.fillWhoLines(null)).toBeNull();
  });
});
