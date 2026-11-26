/** Issue #68: the D4's light bar keeps each effect in its own memory, so the page does not offer the rainbow. */
import { describe, it, expect, vi } from 'vitest';

const answer = { power: 'on', mode: 'solid', rainbow_offered: false };
vi.mock('../api.js', () => ({
  api: { get: vi.fn(async (url) => (url === '/api/led' ? { ...answer } : {})), post: vi.fn(async () => ({})) },
}));

const { initLedControl } = await import('../components/led-control.js');

const page = () => {
  document.body.innerHTML = `<div id="tab-led">
    <span id="preview-state-txt"></span><div id="led-preview-bar"></div>
    <button class="effect-btn" data-effect="solid">Solid</button>
    <button class="effect-btn" data-effect="rainbow">Rainbow</button>
    <button class="profile-pill" data-profile="clean">Clean</button>
    <button class="profile-pill" data-profile="rainbow">Spectrum</button></div>`;
  initLedControl();
};
const rainbow = () => /** @type {HTMLElement} */ (document.querySelector('[data-effect="rainbow"]'));
const spectrum = () => /** @type {HTMLElement} */ (document.querySelector('[data-profile="rainbow"]'));

describe('the rainbow on a bar that keeps its effect', () => {
  it('is hidden where the server says the bar does not take it', async () => {
    answer.rainbow_offered = false;
    page();
    await vi.waitFor(() => expect(rainbow().hidden).toBe(true));
    expect(spectrum().hidden).toBe(true);
    expect(/** @type {HTMLElement} */ (document.querySelector('[data-effect="solid"]')).hidden).toBe(false);
  });

  it('stays on every other bar, and with a server that does not say', async () => {
    answer.rainbow_offered = true;
    page();
    await vi.waitFor(() =>
      expect(document.querySelector('[data-effect="solid"]')?.classList.contains('active')).toBe(true)
    );
    expect(rainbow().hidden).toBe(false);
    delete answer.rainbow_offered;
    page();
    await vi.waitFor(() =>
      expect(document.querySelector('[data-effect="solid"]')?.classList.contains('active')).toBe(true)
    );
    expect(rainbow().hidden).toBe(false);
    expect(spectrum().hidden).toBe(false);
  });
});
