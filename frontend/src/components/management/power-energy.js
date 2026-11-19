/**
 * Power: "Electricity" (re-audit R9). What the UPS feeds, added up from its own readings: today,
 * the last 7 and 30 days, the average, and with a price per kWh what a month costs.
 */
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { formatFixed } from '../../format.js';

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

export function kwh(value) {
  return t('pwe.kwh', '{value} kWh', { value: formatFixed(value || 0, value >= 10 ? 0 : 2) });
}

export function energyNodes(s) {
  if (!s || !s.measuring) {
    return [
      el(
        'p',
        'kb-muted',
        t(
          'pwe.none',
          'Kiboto adds up the electricity used when a UPS reports its power. Nothing has been measured yet: with such a UPS connected, the numbers appear within minutes.'
        )
      ),
    ];
  }
  const dl = el('dl', 'net-dl');
  const row = (label, value) => dl.append(el('dt', '', label), el('dd', '', value));
  row(t('pwe.today', 'Today'), kwh(s.today_kwh));
  row(t('pwe.week', 'Last 7 days'), kwh(s.week_kwh));
  row(t('pwe.month', 'Last 30 days'), kwh(s.month_kwh));
  row(t('pwe.avg', 'On average'), t('pwe.watts', '{value} W', { value: formatFixed(s.avg_watts || 0, 0) }));
  const nodes = [
    el(
      'p',
      'kb-muted',
      t('pwe.what', 'Everything plugged into the UPS, this NAS included. Only time that was measured is counted.')
    ),
    dl,
  ];
  if (s.month_cost != null)
    nodes.push(
      el(
        'p',
        '',
        t('pwe.cost', 'At {price} per kWh that is about {cost} a month.', {
          price: formatFixed(s.price, 2),
          cost: formatFixed(s.month_cost, 2),
        })
      )
    );
  return nodes;
}

export async function renderPowerEnergy(box = document.getElementById('power-energy')) {
  if (!box) return null;
  let s;
  try {
    s = await api.get('/api/ups/energy');
  } catch {
    box.hidden = true;
    return null;
  }
  box.hidden = false;
  const title = el('h3', 'ups-fs13-semi pwh-title', t('pwe.title', 'Electricity'));
  title.id = 'power-energy-title';
  const body = el('div', 'pwh');
  body.append(...energyNodes(s));
  const price = Object.assign(el('input', 'tz-text-input pwe-price'), { type: 'number', min: '0', step: '0.01' });
  price.value = s.price != null ? String(s.price) : '';
  const label = el('label', 'pwe-price-row');
  label.append(el('span', '', t('pwe.price', 'Price per kWh, in your currency')), price);
  price.addEventListener('change', async () => {
    try {
      await api.put('/api/ups/energy/price', { price: price.value === '' ? null : Number(price.value) });
      await renderPowerEnergy(box);
    } catch (e) {
      body.append(
        el('p', 'kb-muted', t('pwe.price_failed', "The price couldn't be saved: {error}", { error: e?.message || '' }))
      );
    }
  });
  box.replaceChildren(title, body, label);
  return s;
}
