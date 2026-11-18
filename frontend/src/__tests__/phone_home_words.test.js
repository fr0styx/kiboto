// The phone home screen follows the language once it has loaded (phone desktop sweep, 17 Nov).
import { describe, it, expect, afterEach } from 'vitest';
import { statusHtml } from '../components/phone-shell.js';
import { renderWeatherUI } from '../components/widgets.js';
import { setLanguage } from '../i18n.js';

describe('phone home words', () => {
  afterEach(async () => {
    await setLanguage('en');
    document.body.innerHTML = '';
  });

  it('the status labels carry their text keys', () => {
    document.body.innerHTML = statusHtml();
    const keys = [...document.querySelectorAll('.phone-stat-label')].map((e) => e.dataset.i18n);
    expect(keys).toEqual(['phone.cpu', 'phone.ram', 'mgmt.sidebar_storage', 'phone.network_now']);
  });

  it('the weather card is drawn again in the new language', async () => {
    document.body.innerHTML =
      '<div id="widget-weather"><span id="w-weather-city"></span><span id="w-weather-icon"></span><span id="w-weather-temp"></span><span id="w-weather-desc"></span><span id="w-weather-range"></span><span id="w-weather-details"></span></div>';
    renderWeatherUI({ code: 0, temp: 13, max: 15, min: 2, humidity: 46, wind: 9 });
    expect(document.getElementById('w-weather-desc').textContent).toBe('Clear Sky');
    await setLanguage('de');
    expect(document.getElementById('w-weather-desc').textContent).not.toBe('Clear Sky');
    expect(document.getElementById('w-weather-city').textContent).toBe('Hier');
  });
});
