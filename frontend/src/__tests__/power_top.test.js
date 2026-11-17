// SET-31, Power stage 3: the first screen of Power from one answer (GET /api/power).
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { powerWord, powerSentence, powerNumbers, whenPowerGoes, comesBack, stateFromReading, renderPowerTop } from '../components/management/power-top.js';
import { fetchAndRenderUpsTelemetry } from '../components/management/ups.js';

afterEach(() => vi.restoreAllMocks());

const RULE = { minutes: 5, battery_pct: 20, timer_sec: 600 };
const KIBOTO = { by: 'kiboto', ok: true };

describe('the status line', () => {
  it('says each state in a word and a sentence', () => {
    expect(powerWord({ state: 'none' })).toBe('No battery backup');
    expect(powerSentence({ state: 'none', switch_off: { by: 'unraid' } })).toBe('Kiboto has not found a UPS (a battery backup). If Unraid watches a UPS itself, Unraid shuts the NAS down.');
    expect(powerSentence({ state: 'none' })).toMatch(/switches off at once/);
    expect(powerWord({ state: 'protected' })).toBe('Protected');
    expect(powerSentence({ state: 'protected', numbers: { battery_pct: 99.6, minutes: 31.2 } })).toBe('On mains power. The UPS battery is 100 % full; the UPS estimates about 31 minutes.');
    expect(powerSentence({ state: 'protected', numbers: {} })).toBe('On mains power, and the UPS is ready.');
    expect(powerWord({ state: 'look' })).toBe('Needs a look');
    expect(powerSentence({ state: 'look', reason: 'switch_off' })).toBe('Nothing can switch this NAS off in a power cut.');
    expect(powerSentence({ state: 'look', reason: 'battery', checks: [{ id: 'battery', ok: false, replace: true }] })).toBe('The UPS says its battery needs replacing.');
    expect(powerSentence({ state: 'look', reason: 'battery', checks: [] })).toBe('The UPS battery is low.');
    expect(powerSentence({ state: 'look', reason: 'readable' })).toBe('A UPS was found, but Kiboto cannot read it.');
    expect(powerSentence({ state: 'unreadable', reason: 'permission' })).toMatch(/USB/);
    expect(powerSentence({ state: 'unreadable' })).toBe('A UPS was found, but Kiboto cannot read it.');
    expect(powerWord({ state: 'cut' })).toBe('The power is out');
    expect(powerSentence({ state: 'cut', numbers: { minutes: 26 }, rule: RULE, switch_off: KIBOTO })).toBe('Your NAS is running on the UPS battery. The UPS estimates about 26 more minutes. Kiboto will shut the NAS down safely when about 5 minutes are left, unless the power comes back first.');
    expect(powerSentence({ state: 'cut', since: 1762900000, numbers: {}, rule: RULE, switch_off: { by: 'unraid', ok: true } })).toMatch(/^Your NAS has been running on the UPS battery since .+ Unraid shuts the NAS down by its own UPS settings/);
    expect(powerSentence({ state: 'cut', drill: true, numbers: {}, rule: RULE, switch_off: KIBOTO })).toMatch(/^Practice run/);
    expect(powerWord({ state: 'shutting' })).toBe('Shutting down');
    expect(powerSentence({ state: 'shutting' })).toMatch(/shutting the NAS down now/);
    expect(powerWord({ state: 'by_hand' })).toBe('Shut the NAS down by hand');
    expect(powerSentence({ state: 'by_hand' })).toMatch(/cannot switch this NAS off/);
    expect(powerWord({ state: 'silent' })).toBe('UPS not answering');
    expect(powerSentence({ state: 'silent' })).toBe('Kiboto cannot reach your UPS any more. Check its cable.');
  });

  it('shows up to three numbers, watts only when known', () => {
    expect(powerNumbers({ state: 'protected', numbers: { battery_pct: 87, minutes: 31, watts: 64.4 } })).toEqual(['Battery 87 %', 'About 31 min', '64 W in use']);
    expect(powerNumbers({ state: 'protected', numbers: { battery_pct: 87, minutes: null, watts: null } })).toEqual(['Battery 87 %']);
    expect(powerNumbers({ state: 'none', numbers: { battery_pct: 87 } })).toEqual([]);
    expect(powerNumbers(null)).toEqual([]);
  });
});

describe('when the power goes out', () => {
  it('names who switches the NAS off, in red when nothing can', () => {
    const k = whenPowerGoes({ state: 'protected', switch_off: KIBOTO, rule: RULE, checks: [] });
    expect(k.line).toBe('Kiboto shuts your NAS down safely when the battery is nearly empty.');
    expect(k.steps).toHaveLength(4);
    expect(k.steps[1]).toMatch(/about 5 minutes or 20 % left/);
    expect(k.steps[3]).toBe('Last, Kiboto switches the NAS off.');
    const host = whenPowerGoes({ state: 'protected', switch_off: { by: 'truenas', ok: true }, rule: RULE, checks: [] });
    expect(host.line).toMatch(/^TrueNAS shuts your NAS down/);
    expect(host.steps[3]).toBe('Last, TrueNAS switches the NAS off, by its own UPS settings.');
    const nobody = whenPowerGoes({ state: 'look', switch_off: { by: 'kiboto', ok: false, detail: 'No host shutdown command is mounted.' }, rule: RULE, checks: [] });
    expect(nobody.bad).toBe(true);
    expect(nobody.steps[3]).toBe('Nothing can switch this NAS off: No host shutdown command is mounted.');
    const blind = whenPowerGoes({ state: 'protected', switch_off: KIBOTO, rule: RULE, checks: [{ id: 'rule', ok: true, blind: true }] });
    expect(blind.steps[1]).toMatch(/^Kiboto keeps everything running for 10 minutes on battery/);
    const none = whenPowerGoes({ state: 'none' });
    expect(none.line).toBe('Without a battery backup, the NAS switches off at once.');
    expect(none.steps).toHaveLength(3);
  });
});

describe('will it start again by itself', () => {
  it('is proven only after a real power cut', () => {
    expect(comesBack({}).line).toBe('Not proven yet.');
    expect(comesBack({ comes_back: { answer: 'host', host: 'Unraid' } }).line).toBe('Unraid decides this.');
    expect(comesBack({ comes_back: { answer: 'proven', at: 1762900000 } }).line).toMatch(/^Yes, proven on /);
    expect(comesBack({ comes_back: { answer: 'no', at: 1762900000 } }).line).toMatch(/^No: after the power cut on /);
    expect(comesBack({}).detail).toMatch(/Restore on AC power loss/);
  });
});

describe('the first screen', () => {
  it('works out a state from a bare reading for an older server', () => {
    expect(stateFromReading(null).state).toBe('none');
    expect(stateFromReading({ available: true, permission_error: true }).reason).toBe('permission');
    expect(stateFromReading({ available: false }).state).toBe('none');
    expect(stateFromReading({ available: true, on_battery: true, time_left_min: 12 }).state).toBe('cut');
    expect(stateFromReading({ available: true, status: 'OL RB' }).checks[0].replace).toBe(true);
    expect(stateFromReading({ available: true, status: 'OL', battery_charge_pct: 15 }).state).toBe('look');
    expect(stateFromReading({ available: true, status: 'OL', battery_charge_pct: 90 }).state).toBe('protected');
  });

  it('draws the three answers and keeps an open section open', () => {
    document.body.innerHTML = '<div id="ups-status-line"></div>';
    const box = /** @type {HTMLElement} */ (document.getElementById('ups-status-line'));
    const s = { state: 'by_hand', numbers: { battery_pct: 4 }, switch_off: { by: 'kiboto', ok: false, detail: 'none' }, rule: RULE, checks: [] };
    renderPowerTop(box, s);
    expect(box.dataset.state).toBe('cut');
    expect(box.dataset.power).toBe('by_hand');
    expect(box.querySelector('#ups-status-word')?.textContent).toBe('Shut the NAS down by hand');
    expect(box.querySelectorAll('.pw-number')).toHaveLength(1);
    expect(box.querySelector('.pw-when')?.classList.contains('is-bad')).toBe(true);
    box.querySelector('.pw-when')?.setAttribute('open', '');
    renderPowerTop(box, s);
    expect(box.querySelector('.pw-when')?.hasAttribute('open')).toBe(true);
    expect(box.querySelector('.pw-back')?.hasAttribute('open')).toBe(false);
    renderPowerTop(null, s); // no box: nothing happens
  });

  it('the page asks /api/power and folds the rest away without a UPS', async () => {
    document.body.innerHTML = '<div id="mgmt-sec-ups"><div id="ups-status-line"></div><section id="power-check" hidden></section><div id="ups-cockpit-config-section"></div></div>';
    vi.spyOn(api, 'get').mockImplementation(async (url) => (url === '/api/power'
      ? { state: 'protected', numbers: { battery_pct: 90, minutes: 40 }, switch_off: KIBOTO, rule: RULE, checks: [], tests: { practice: { at: 1762900000, ok: true, detail: 'Kiboto shuts the server down.' } } }
      : url === '/api/ups' ? { available: true, status: 'OL', battery_charge_pct: 90 } : {}));
    await fetchAndRenderUpsTelemetry();
    const pane = /** @type {HTMLElement} */ (document.getElementById('mgmt-sec-ups'));
    expect(pane.dataset.upsState).toBe('mains');
    expect(document.getElementById('ups-status-word')?.textContent).toBe('Protected');
    expect(document.getElementById('ups-practice-line')?.hidden).toBe(false);
    expect(document.getElementById('ups-show-setup')?.hidden).toBe(true);
  });
});

describe("one question after a real power cut", () => {
  it("asks whether the NAS switched on by itself and passes the answer on", () => {
    expect(comesBack({ comes_back: { answer: "ask", at: 1762900000 } }).line).toMatch(/^After the power cut on .+: did the NAS switch on again by itself\?$/);
    document.body.innerHTML = "<div id=\"b\"></div>";
    const box = /** @type {HTMLElement} */ (document.getElementById("b"));
    const answers = [];
    renderPowerTop(box, { state: "protected", numbers: {}, switch_off: { by: "kiboto", ok: true }, rule: RULE, checks: [], comes_back: { answer: "ask", at: 1762900000 } }, (yes) => answers.push(yes));
    expect(box.querySelector(".pw-back")?.hasAttribute("open")).toBe(true);
    /** @type {HTMLElement} */ (box.querySelector("[data-back=\"yes\"]")).click();
    /** @type {HTMLElement} */ (box.querySelector("[data-back=\"no\"]")).click();
    expect(answers).toEqual([true, false]);
  });
});
