// SET-31, Power stage 5: the answer to "did the NAS switch on by itself?" goes to the server.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { fetchAndRenderUpsTelemetry } from '../components/management/ups.js';

afterEach(() => vi.restoreAllMocks());
const flush = () => new Promise((r) => setTimeout(r, 0));

const ASK = {
  state: 'protected',
  numbers: {},
  switch_off: { by: 'kiboto', ok: true },
  rule: { minutes: 5, battery_pct: 20, timer_sec: 300 },
  checks: [],
  comes_back: { answer: 'ask', at: 1762900000 },
};

describe('the answer about the last power cut', () => {
  it('is sent, and a refusal is said', async () => {
    document.body.innerHTML =
      '<div id="mgmt-sec-ups"><div id="ups-status-line"></div><section id="power-check"></section></div>';
    vi.spyOn(api, 'get').mockImplementation(async (url) =>
      url === '/api/power' ? ASK : url === '/api/ups' ? { available: true, status: 'OL' } : {}
    );
    const post = vi.spyOn(api, 'post').mockResolvedValue({ answer: 'proven', at: 1762900000 });
    await fetchAndRenderUpsTelemetry();
    /** @type {HTMLElement} */ (document.querySelector('[data-back="yes"]')).click();
    await flush();
    expect(post).toHaveBeenCalledWith('/api/power/comes-back', { by_itself: true });
    post.mockRejectedValue(new Error('There is no power cut to answer about.'));
    await fetchAndRenderUpsTelemetry();
    /** @type {HTMLElement} */ (document.querySelector('[data-back="no"]')).click();
    await flush();
    expect(post).toHaveBeenLastCalledWith('/api/power/comes-back', { by_itself: false });
  });
});
