// The load moved from the Hardware page's Host tab to Activity → Right now (Hardware 3).
import { describe, it, expect, afterEach } from 'vitest';
import { loadLine, renderRightNow } from '../components/right-now.js';
import { setLanguage } from '../i18n.js';

describe('Right now: the load', () => {
  afterEach(async () => {
    await setLanguage('en');
    document.body.innerHTML = '';
  });

  it("says the load over 1, 5 and 15 minutes, in the reader's numbers", async () => {
    expect(loadLine({ cpu: { load_avg: [0.52, 0.48, 0.4] } })).toBe('Load (1, 5, 15 min): 0.52 · 0.48 · 0.40');
    await setLanguage('de');
    expect(loadLine({ cpu: { load_avg: [1.5, 'x', 0] } })).toBe('Last (1, 5, 15 Min.): 1,50 · 0,00 · 0,00');
  });

  it('says nothing without a load', () => {
    expect(loadLine(null)).toBe('');
    expect(loadLine({ cpu: {} })).toBe('');
    expect(loadLine({ cpu: { load_avg: [] } })).toBe('');
  });

  it('draws the line under the rest', () => {
    document.body.innerHTML = '<div id="right-now" hidden></div>';
    renderRightNow(document.getElementById('right-now'), { cpu: { util: 3, load_avg: [0.1, 0.2, 0.3] } }, []);
    expect(document.querySelector('.right-now-load').textContent).toBe('Load (1, 5, 15 min): 0.10 · 0.20 · 0.30');
    renderRightNow(document.getElementById('right-now'), { cpu: { util: 3 } }, []);
    expect(document.querySelector('.right-now-load')).toBeNull();
  });
});
