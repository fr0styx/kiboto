// The weather card asks for a place on first use instead of showing another city's weather
// (owner's decision, 17 Nov). "Find it for me" uses the time zone; when that finds nothing, it asks again.
import { describe, it, expect, afterEach, vi } from 'vitest';
import {
  fetchWeather,
  renderWeatherUI,
  renderWeatherAsk,
  weatherPlaceSet,
  openWeatherPlace,
  saveWidgetConfig,
  loadWidgetConfig,
} from '../components/widgets.js';
import { setLanguage } from '../i18n.js';

const CARD = `<div id="widget-weather"><span id="w-weather-city"></span>
  <div id="w-weather-body"><span id="w-weather-icon"></span><span id="w-weather-temp"></span><span id="w-weather-desc"></span>
  <span id="w-weather-range"></span><span id="w-weather-details"></span></div>
  <div id="w-weather-ask" hidden><span id="w-weather-ask-text"></span><button id="w-weather-ask-btn"></button></div></div>`;

const FORECAST = {
  current: { temperature_2m: 12, relative_humidity_2m: 50, weather_code: 0, wind_speed_10m: 8 },
  daily: {},
};
const reply = (body) => Promise.resolve({ ok: true, json: () => Promise.resolve(body) });

function setPlace(cfg) {
  localStorage.clear();
  loadWidgetConfig();
  document.body.innerHTML = CARD;
  saveWidgetConfig({ enabled: true, weatherCity: '', weatherLat: null, weatherLon: null, weatherAuto: false, ...cfg });
  document.body.innerHTML = CARD;
}
const asking = () =>
  !document.getElementById('w-weather-ask').hidden &&
  document.getElementById('w-weather-body').style.display === 'none';

describe('weather card asks for a place', () => {
  afterEach(async () => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    await setLanguage('en');
    localStorage.clear();
    document.body.innerHTML = '';
    delete window.openManagementWindow;
  });

  it('knows when a place is set', () => {
    expect(weatherPlaceSet({})).toBe(false);
    expect(weatherPlaceSet({ weatherCity: '  ' })).toBe(false);
    expect(weatherPlaceSet({ weatherCity: 'Halifax' })).toBe(true);
    expect(weatherPlaceSet({ weatherLat: 1, weatherLon: 2 })).toBe(true);
    expect(weatherPlaceSet({ weatherAuto: true })).toBe(true);
    expect(weatherPlaceSet(null)).toBe(false);
  });

  it('with no place it asks and fetches nothing', async () => {
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    setPlace({});
    await fetchWeather(true);
    expect(fetch).not.toHaveBeenCalled();
    expect(asking()).toBe(true);
    expect(document.getElementById('w-weather-ask-text').textContent).toBe('Choose a place to see its weather.');
    expect(document.getElementById('w-weather-city').hidden).toBe(true);
  });

  it('"find it for me" that finds nothing asks again, never a stand-in city', async () => {
    const fetch = vi.fn(() => reply({ results: [] }));
    vi.stubGlobal('fetch', fetch);
    setPlace({ weatherAuto: true });
    await fetchWeather(true);
    expect(fetch.mock.calls.every(([url]) => !String(url).includes('forecast'))).toBe(true);
    expect(asking()).toBe(true);
    expect(document.getElementById('w-weather-ask-text').textContent).toMatch(/Could not tell where this is/);
  });

  it('"find it for me" uses the time zone city', async () => {
    const fetch = vi.fn((url) =>
      String(url).includes('geocoding')
        ? reply({ results: [{ latitude: 44.6, longitude: -63.6, name: 'Halifax' }] })
        : reply(FORECAST)
    );
    vi.stubGlobal('fetch', fetch);
    vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({ timeZone: 'America/Halifax' });
    setPlace({ weatherAuto: true });
    await fetchWeather(true);
    expect(fetch.mock.calls.some(([url]) => String(url).includes('latitude=44.6'))).toBe(true);
    expect(asking()).toBe(false);
    expect(document.getElementById('w-weather-city').textContent).toBe('Halifax');
    vi.restoreAllMocks();
  });

  it('a chosen place that cannot be found asks, without trying the time zone', async () => {
    const fetch = vi.fn(() => reply({ results: [] }));
    vi.stubGlobal('fetch', fetch);
    setPlace({ weatherCity: 'Nowhere' });
    await fetchWeather(true);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(asking()).toBe(true);
  });

  it('weather drawn after asking hides the question, and the question follows the language', async () => {
    document.body.innerHTML = CARD;
    renderWeatherAsk('none');
    await setLanguage('de');
    expect(document.getElementById('w-weather-ask-text').textContent).toBe(
      'Wählen Sie einen Ort, um sein Wetter zu sehen.'
    );
    expect(document.getElementById('w-weather-ask-btn').textContent).toBe('Ort wählen');
    renderWeatherUI({ code: 0, tempC: 10, highC: 12, lowC: 4, humidity: 40, wind: 5, city: 'Kiel' });
    expect(asking()).toBe(false);
    expect(document.getElementById('w-weather-city').hidden).toBe(false);
    await setLanguage('en');
    expect(document.getElementById('w-weather-ask').hidden).toBe(true);
  });

  it('the button opens Widget settings at the place field', () => {
    vi.useFakeTimers();
    document.body.innerHTML = CARD + '<input id="widget-weather-city-input">';
    const open = vi.fn();
    window.openManagementWindow = open;
    openWeatherPlace();
    vi.advanceTimersByTime(200);
    expect(open).toHaveBeenCalledWith('mgmt-sec-wallpaper', 'mgmt-pane-widgets');
    expect(document.activeElement.id).toBe('widget-weather-city-input');
    vi.advanceTimersByTime(1600);
    expect(document.activeElement.classList.contains('element-focus-pulse')).toBe(false);
  });

  it('opening does nothing when the settings window is not there', () => {
    expect(() => openWeatherPlace()).not.toThrow();
  });
});
