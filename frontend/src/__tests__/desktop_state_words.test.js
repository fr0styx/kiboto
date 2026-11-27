// The storage card's state in the reader's language (bare-desktop sweep, 17 Nov).
import { describe, it, expect, afterEach, vi } from 'vitest';
import { poolStateWord, initWidgets } from '../components/widgets.js';
import { KibotoEventBus } from '../event-bus.js';
import { setLanguage } from '../i18n.js';

describe('storage card state', () => {
  afterEach(async () => {
    await setLanguage('en');
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
  });

  it("Unraid's states in words, another as reported", async () => {
    expect(poolStateWord('STARTED')).toBe('Running');
    expect(poolStateWord('STOPPED')).toBe('Stopped');
    expect(poolStateWord('STANDALONE')).toBe('Online');
    expect(poolStateWord(undefined)).toBe('Online');
    expect(poolStateWord('NEW_ARRAY')).toBe('NEW_ARRAY');
    await setLanguage('de');
    expect(poolStateWord('STANDALONE')).toBe('Bereit');
  });

  it('the card shows it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }));
    document.body.innerHTML =
      '<div id="widget-storage"><span id="w-storage-val"></span><div id="w-storage-bar"></div><span id="w-storage-status"></span></div>';
    initWidgets();
    KibotoEventBus.emit('stats:updated', {
      storage: { used: '75GB', total: '97GB', pct: 77 },
      unraid: { state: 'STARTED' },
    });
    await vi.waitFor(() => expect(document.getElementById('w-storage-status').textContent).toBe('Running'));
  });
});
