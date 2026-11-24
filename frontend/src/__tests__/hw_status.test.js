import { describe, it, expect } from 'vitest';
import { coolingLine, coolingStatus, renderCoolingStatus } from '../components/hw-status.js';

const awake = (temp) => ({ dev: 'sda', temp, standby: false });
const base = (over = {}) => ({
  cpu: { temp: 44 },
  disks: [awake(38), { dev: 'sdb', temp: null, standby: true }, { dev: 'nvme0n1', temp: 36 }],
  fans: [1066, 1082, 3400],
  fan_control: { driver_mode: 'mmio', zone1_pwm: 75, nvme_temp: 36, profile: 'balanced' },
  ...over,
});

describe('cooling in plain words (Hardware 2, the status sentence)', () => {
  it('names each part with a temperature and a word, and the fans with their speed', () => {
    const s = coolingStatus(base());
    expect(s.level).toBe('ok');
    expect(s.rows.map((r) => [r.label, r.value])).toEqual([
      ['Processor', '44 °C · fine'],
      ['Drives', '38 °C · fine'],
      ['Fast drives (NVMe)', '36 °C · fine'],
      ['Fans', '41 % · 1,066 rpm'],
    ]);
  });

  it('says when the drives sleep and the fans stand still', () => {
    const s = coolingStatus(
      base({ disks: [{ dev: 'sda', temp: null, standby: true }], fan_control: { driver_mode: 'mmio', zone1_pwm: 0 } })
    );
    expect(s.rows.find((r) => r.id === 'drives').value).toBe('asleep');
    expect(s.rows.find((r) => r.id === 'fans').value).toBe('stopped while the drives sleep');
  });

  it('warm is amber, too hot is red and names what runs the fans at full speed', () => {
    expect(coolingStatus(base({ cpu: { temp: 74 } })).level).toBe('warm');
    const hot = coolingStatus(base({ cpu: { temp: 88 }, fan_control: { driver_mode: 'mmio', zone1_pwm: 183 } }));
    expect(hot.level).toBe('hot');
    expect(hot.rows.find((r) => r.id === 'cpu').value).toBe('88 °C · too hot');
    expect(hot.rows.find((r) => r.id === 'fans').value).toBe('full speed: the processor is hot');
    const drive = coolingStatus(base({ disks: [awake(57)], fan_control: { driver_mode: 'mmio', zone1_pwm: 183 } }));
    expect(drive.rows.find((r) => r.id === 'fans').value).toBe('full speed: a drive is hot');
  });

  it('leaves out what it cannot read', () => {
    expect(coolingStatus(null)).toBe(null);
    expect(coolingStatus({})).toBe(null);
    const s = coolingStatus({ cpu: { temp: 50 }, fan_control: { driver_mode: 'none', zone1_pwm: 58 } });
    expect(s.rows.map((r) => r.id)).toEqual(['cpu']); // no fan control here: no fan row
  });

  it('the Overview tile: the mode and the hottest drive, or that the drives sleep', () => {
    expect(coolingLine(base())).toBe('Balanced · 38 °C');
    expect(coolingLine(base({ disks: [{ dev: 'sda', standby: true }] }))).toBe('Balanced · drives asleep');
    expect(coolingLine(base({ disks: [] }))).toBe('Balanced');
    expect(coolingLine(base({ fan_control: { driver_mode: 'none' } }))).toBe('');
    expect(coolingLine({})).toBe('');
  });

  it('draws the list with a word and a dot per row', () => {
    document.body.innerHTML = '<section id="hw-status" hidden><ul id="hw-status-rows"></ul></section>';
    renderCoolingStatus(base());
    const box = document.getElementById('hw-status');
    expect(box.hidden).toBe(false);
    expect(box.dataset.level).toBe('ok');
    const items = [...document.querySelectorAll('#hw-status-rows li')];
    expect(items).toHaveLength(4);
    expect(items[0].textContent).toBe('Processor44 °C · fine');
    expect(items[0].querySelector('.hw-st-dot').getAttribute('aria-hidden')).toBe('true');
    renderCoolingStatus(null);
    expect(box.hidden).toBe(true);
    document.body.innerHTML = '';
    renderCoolingStatus(base()); // no list on the page: nothing happens
  });
});
