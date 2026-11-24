import { describe, it, expect } from 'vitest';
import { state } from '../state.js';
import { applyTypedPoint, renderCurveFields } from '../components/fan-control.js';

const BALANCED = [
  [30, 0],
  [36, 32],
  [42, 60],
  [47, 84],
  [53, 100],
  [60, 100],
];

describe('the curve typed in (Hardware 2)', () => {
  it('keeps a typed point in order, like a dragged one', () => {
    expect(applyTypedPoint(BALANCED, 2, 44, 70)[2]).toEqual([44, 70]);
    expect(applyTypedPoint(BALANCED, 2, 50, 60)[2]).toEqual([46, 60]); // not past the next point
    expect(applyTypedPoint(BALANCED, 2, 30, 60)[2]).toEqual([37, 60]); // nor before the one before
    expect(applyTypedPoint(BALANCED, 2, 42, 95)[2]).toEqual([42, 84]); // never faster than a hotter point
    expect(applyTypedPoint(BALANCED, 2, 42, 10)[2]).toEqual([42, 32]); // nor slower than a cooler one
    expect(applyTypedPoint(BALANCED, 0, 34, 20)[0]).toEqual([30, 20]); // the ends stay at 30 and 60 °C
    expect(applyTypedPoint(BALANCED, 5, 58, 100)[5]).toEqual([60, 100]);
    expect(applyTypedPoint(BALANCED, 3, 'x', 'y')[3]).toEqual([47, 84]); // what is not a number keeps the old value
    expect(BALANCED[2]).toEqual([42, 60]); // the curve given is not changed
  });

  it('shows the six points as labelled fields, the ends fixed', () => {
    document.body.innerHTML = '<div id="curve-fields"></div>';
    state.setCurvePoints(BALANCED.map((p) => [...p]));
    renderCurveFields();
    const inputs = /** @type {HTMLInputElement[]} */ ([...document.querySelectorAll('#curve-fields input')]);
    expect(inputs).toHaveLength(12);
    expect(inputs[2].value).toBe('36');
    expect(inputs[3].value).toBe('32');
    expect(inputs[0].readOnly && inputs[10].readOnly && !inputs[2].readOnly).toBe(true);
    expect(inputs[2].getAttribute('aria-label')).toBe('Point 2: temperature in °C');
    state.setCurvePoints(applyTypedPoint(state.curvePoints, 1, 38, 40));
    inputs[3].focus();
    renderCurveFields(); // a field being typed in keeps what is typed
    expect(inputs[2].value).toBe('38');
    document.body.innerHTML = '';
    renderCurveFields(); // no fields on the page: nothing happens
  });
});
