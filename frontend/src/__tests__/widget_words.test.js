// Desktop widgets in the reader's language: the network card's port (17 Nov).
import { describe, it, expect, afterEach, vi } from 'vitest';
import { ifaceWord, initWidgets } from '../components/widgets.js';
import { ZettEventBus } from '../event-bus.js';
import { setLanguage } from '../i18n.js';

describe('widget words', () => {
  afterEach(async () => {
    await setLanguage('en');
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
  });

  it('"combined" is every port, in words; a real port keeps its name', async () => {
    expect(ifaceWord('combined')).toBe('All ports');
    expect(ifaceWord('eth0')).toBe('eth0');
    await setLanguage('de');
    expect(ifaceWord('combined')).toBe('Alle Anschlüsse');
  });

  it('the network card shows it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }));
    document.body.innerHTML =
      '<div id="widget-network"><span id="w-net-rx"></span><span id="w-net-tx"></span><span id="w-net-iface"></span></div>';
    initWidgets();
    ZettEventBus.emit('stats:updated', { net: { iface: 'combined', rx: '1 KB/s', tx: '0 B/s' } });
    await vi.waitFor(() => expect(document.getElementById('w-net-iface').textContent).toBe('All ports'));
    expect(document.getElementById('w-net-rx').textContent).toBe('1 KB/s');
  });
});
