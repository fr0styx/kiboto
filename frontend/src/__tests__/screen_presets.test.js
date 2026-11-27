/** #71: the front screen's preset cards and "Save as My Preset" did nothing. */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const post = vi.fn(async () => ({ layout: { version: 7 } }));
vi.mock('../api.js', () => ({ api: { post, get: vi.fn(async () => ({})) } }));
const mp = await import('../components/mini-preview.js');
const { state } = await import('../state.js');

const drawer = () => {
  document.body.innerHTML = `<span id="preset-state-badge"></span>
    <div class="grid">${['default', 'thermal', 'storage', 'disks-only']
      .map((k) => `<button class="preset-btn-card" data-preset="${k}"><span class="preset-name">${k}</span></button>`)
      .join('')}</div>
    <button id="btn-save-custom-preset"><span>Save as My Preset</span></button>`;
};

describe('front-screen presets', () => {
  beforeEach(() => {
    post.mockClear();
    mp.setupScreenPresets();
    drawer(); // the drawer arrives after the page: the clicks are heard at the page
  });

  it('a card puts its modules on the screen and saves them; Disks Only is shown as active', async () => {
    /** @type {HTMLElement} */ (document.querySelector('[data-preset="disks-only"] span')).click();
    await vi.waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1].vis).toMatchObject(mp.PRESETS['disks-only']);
    expect(document.querySelector('[data-preset="disks-only"]')?.classList.contains('active')).toBe(true);
    expect(document.getElementById('preset-state-badge')?.textContent).toBe('DISKS ONLY');
  });

  it('"Save as My Preset" keeps the layout as a card that brings it back', async () => {
    await mp.applyScreenPreset('thermal');
    post.mockClear();
    /** @type {HTMLElement} */ (document.querySelector('#btn-save-custom-preset span')).click();
    await vi.waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1].my_preset.vis).toMatchObject(mp.PRESETS.thermal);
    const mine = document.querySelector('[data-preset="mine"]');
    expect(mine?.textContent).toContain('My preset');
    await mp.applyScreenPreset('storage');
    post.mockClear();
    /** @type {HTMLElement} */ (mine).click();
    await vi.waitFor(() => expect(post).toHaveBeenCalled());
    expect(state.dashVis).toMatchObject(mp.PRESETS.thermal);
    expect(post.mock.calls[0][1].my_preset).toBeUndefined(); // an ordinary save keeps it as it is
  });

  it('an unknown preset changes nothing', async () => {
    await mp.applyScreenPreset('nonsense');
    expect(post).not.toHaveBeenCalled();
  });
});
