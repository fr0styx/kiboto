// Re-audit R9: electricity on the Power page.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { energyNodes, renderPowerEnergy, kwh } from '../components/management/power-energy.js';

const S = {
  measuring: true,
  today_kwh: 1.234,
  week_kwh: 8.4,
  month_kwh: 36.2,
  avg_watts: 50.3,
  price: null,
  month_cost: null,
};

describe('electricity on Power', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('writes the amounts, and says so when nothing was measured', () => {
    expect(kwh(1.234)).toBe('1.23 kWh');
    expect(kwh(36.2)).toBe('36 kWh');
    expect(kwh(undefined)).toBe('0.00 kWh');
    const text = energyNodes(S)
      .map((n) => n.textContent)
      .join(' ');
    expect(text).toContain('Today1.23 kWh');
    expect(text).toContain('Last 7 days8.40 kWh');
    expect(text).toContain('Last 30 days36 kWh');
    expect(text).toContain('On average50 W');
    expect(text).toContain('Everything plugged into the UPS');
    expect(text).not.toContain('a month');
    expect(energyNodes({ measuring: false })[0].textContent).toContain('Nothing has been measured yet');
    expect(energyNodes(null).length).toBe(1);
    expect(energyNodes({ ...S, price: 0.35, month_cost: 12.68 }).pop().textContent).toBe(
      'At 0.35 per kWh that is about 12.68 a month.'
    );
  });

  it('draws the section, saves the price and draws again with the cost', async () => {
    document.body.innerHTML = '<section id="power-energy" hidden></section>';
    const get = vi
      .spyOn(api, 'get')
      .mockResolvedValueOnce(S)
      .mockResolvedValueOnce({ ...S, price: 0.35, month_cost: 12.68 });
    const put = vi.spyOn(api, 'put').mockResolvedValue({ price: 0.35 });
    await renderPowerEnergy();
    const box = document.getElementById('power-energy');
    expect(box.hidden).toBe(false);
    expect(box.querySelector('h3').textContent).toBe('Electricity');
    const price = box.querySelector('input');
    expect(price.value).toBe('');
    price.value = '0.35';
    price.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(put).toHaveBeenCalledWith('/api/ups/energy/price', { price: 0.35 });
    await vi.waitFor(() => expect(box.textContent).toContain('about 12.68 a month'));
    expect(box.querySelector('input').value).toBe('0.35');
  });

  it('an empty price clears it; a failed save says so; no right hides the section', async () => {
    document.body.innerHTML = '<section id="power-energy" hidden></section>';
    vi.spyOn(api, 'get').mockResolvedValue({ ...S, price: 0.35, month_cost: 12.68 });
    const put = vi.spyOn(api, 'put').mockResolvedValueOnce({}).mockRejectedValueOnce(new Error('no right'));
    await renderPowerEnergy();
    let price = document.querySelector('#power-energy input');
    price.value = '';
    price.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(put).toHaveBeenCalledWith('/api/ups/energy/price', { price: null }));
    await vi.waitFor(() => expect(document.querySelector('#power-energy input')).not.toBe(price));
    price = document.querySelector('#power-energy input');
    price.value = '0.5';
    price.dispatchEvent(new Event('change'));
    await vi.waitFor(() =>
      expect(document.getElementById('power-energy').textContent).toContain("couldn't be saved: no right")
    );
    vi.spyOn(api, 'get').mockRejectedValue(new Error('403'));
    expect(await renderPowerEnergy()).toBeNull();
    expect(document.getElementById('power-energy').hidden).toBe(true);
    expect(await renderPowerEnergy(null)).toBeNull();
  });

  it('a UPS that reports only a percentage asks for its rated power, saves it and goes on', async () => {
    document.body.innerHTML = '<section id="power-energy" hidden></section>';
    const loadOnly = { measuring: false, load_only: true, rated_watts: null, price: null };
    expect(energyNodes(loadOnly)[0].textContent).toContain('reports its load only as a percentage');
    const get = vi
      .spyOn(api, 'get')
      .mockResolvedValueOnce(loadOnly)
      .mockResolvedValueOnce({ ...loadOnly, rated_watts: 900 })
      .mockResolvedValue({ ...loadOnly, rated_watts: 900 });
    const put = vi.spyOn(api, 'put').mockResolvedValueOnce({}).mockRejectedValueOnce(new Error('no right'));
    await renderPowerEnergy();
    const box = document.getElementById('power-energy');
    const inputs = box.querySelectorAll('input');
    expect(inputs.length).toBe(2); // the rated power, then the price
    expect(box.querySelectorAll('label')[0].textContent).toContain('Rated power of the UPS');
    inputs[0].value = '900';
    inputs[0].dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(put).toHaveBeenCalledWith('/api/ups/energy/rated-power', { watts: 900 });
    // with the rated power known the page waits for the first readings, and the field stays to change it
    await vi.waitFor(() => expect(box.textContent).toContain('Nothing has been measured yet'));
    const again = box.querySelectorAll('input')[0];
    expect(again.value).toBe('900');
    again.value = '';
    again.dispatchEvent(new Event('change'));
    await vi.waitFor(() => expect(box.textContent).toContain("rated power couldn't be saved: no right"));
    expect(put).toHaveBeenLastCalledWith('/api/ups/energy/rated-power', { watts: null });
  });
});
