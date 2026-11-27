/** #71, a D4 whose host runs the fans and whose backlight Kiboto cannot write. */
import { describe, it, expect, vi } from 'vitest';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showActionToast: vi.fn(),
  showPromptToast: vi.fn(),
  showConfirmToast: vi.fn(),
}));
vi.mock('../components/dock.js', () => ({ applyDockSettings: vi.fn() }));
const { coolingLine, coolingStatus, kibotoRunsFans } = await import('../components/hw-status.js');
const { updateFanCurveWorkstation } = await import('../components/fan-control.js');
const { brightnessPossible } = await import('../components/settings.js');

describe('fans the host runs itself', () => {
  const stats = {
    cpu: { temp: 44 },
    disks: [{ dev: 'sda', temp: 38, standby: false }],
    fans: [3010, 2980],
    fan_control: { driver_mode: 'host', zone1_pwm: 150, profile: 'auto' },
  };

  it('shows no speed or mode of Kiboto for them', () => {
    expect(kibotoRunsFans({ driver_mode: 'host' })).toBe(false);
    expect(kibotoRunsFans({ driver_mode: 'none' })).toBe(false);
    expect(kibotoRunsFans({ driver_mode: 'hwmon' })).toBe(true);
    expect(kibotoRunsFans(null)).toBe(false);
    expect(coolingStatus(stats)?.rows.map((r) => r.id)).not.toContain('fans');
    expect(coolingLine(stats)).toBe('');
  });

  it('the fan window says the system runs them', () => {
    document.body.innerHTML = '<span id="fan-status-badge"></span>';
    updateFanCurveWorkstation({ fan_control: { driver_mode: 'host' } });
    const badge = document.getElementById('fan-status-badge');
    expect(badge?.textContent).toBe('RUN BY YOUR SYSTEM');
    expect(badge?.title).toBe('Your system runs the fans; Kiboto only shows their speed.');
  });
});

describe('a backlight Kiboto cannot set', () => {
  it('turns brightness and night dimming off, with a word why, and back on', () => {
    document.body.innerHTML = `<div class="slider-row"><input type="range" id="screen-bri-slider"></div>
      <input type="checkbox" id="screen-night-toggle"><input type="range" id="screen-night-bri">`;
    brightnessPossible(false);
    const off = ['screen-bri-slider', 'screen-night-toggle', 'screen-night-bri'].map(
      (id) => /** @type {HTMLInputElement} */ (document.getElementById(id)).disabled
    );
    expect(off).toEqual([true, true, true]);
    expect(document.getElementById('screen-bri-unavailable')?.textContent).toBe(
      "This screen's brightness can't be changed from Kiboto here."
    );
    brightnessPossible(false); // once
    expect(document.querySelectorAll('#screen-bri-unavailable').length).toBe(1);
    brightnessPossible(true);
    expect(document.getElementById('screen-bri-unavailable')).toBeNull();
    expect(/** @type {HTMLInputElement} */ (document.getElementById('screen-bri-slider')).disabled).toBe(false);
  });
});
