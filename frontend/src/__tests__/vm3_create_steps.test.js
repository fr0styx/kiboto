/** VMs report stage 3: a new machine in three steps, What to install → How big → More. */
import { describe, it, expect, beforeEach } from 'vitest';
import { STEPS, stepNames, stepsHtml, checkName, showStep, installSteps } from '../components/vm/create-steps.js';

const DIALOG = () => `<div class="smart-modal-backdrop" id="m">
  ${stepsHtml()}
  <div data-vm-step="1"><input id="vm-create-name"><div id="vm-create-name-rule"></div></div>
  <div data-vm-step="2"><input type="range" id="ram"></div>
  <div data-vm-step="3"><select id="bridge"><option>br0</option></select></div>
  <div class="smart-modal-footer"><button id="vm-create-cancel"></button><button id="vm-create-submit"></button></div>
</div>`;
const m = () => document.getElementById('m');
const $ = (id) => document.getElementById(id);

describe('new machine in three steps (VMs stage 3)', () => {
  beforeEach(() => {
    document.body.innerHTML = DIALOG();
  });

  it('names the three steps in order', () => {
    expect(STEPS).toBe(3);
    expect(stepNames()).toEqual(['What to install', 'How big', 'More']);
    expect([...document.querySelectorAll('[data-vm-step-label]')].map((li) => li.textContent.trim())).toEqual([
      '1 What to install',
      '2 How big',
      '3 More',
    ]);
  });

  it('starts on step 1 with Next; Create waits for the last step', () => {
    expect(installSteps(m())).toBe(1);
    expect(m().dataset.vmAt).toBe('1');
    expect($('vm-create-back').hidden).toBe(true);
    expect($('vm-create-next').hidden).toBe(false);
    expect($('vm-create-submit').hidden).toBe(true);
    expect(document.querySelector('[data-vm-step-label="1"]').getAttribute('aria-current')).toBe('step');
    installSteps(m()); // a second call adds no second pair of buttons
    expect(document.querySelectorAll('#vm-create-next')).toHaveLength(1);
  });

  it('Next needs a name the server takes, and says so at the field', () => {
    installSteps(m());
    $('vm-create-name').value = 'a';
    $('vm-create-next').click();
    expect(m().dataset.vmAt).toBe('1');
    expect($('vm-create-name').getAttribute('aria-invalid')).toBe('true');
    expect($('vm-create-name-rule').classList.contains('is-wrong')).toBe(true);
    $('vm-create-name').value = 'ubuntu-dev';
    $('vm-create-name').dispatchEvent(new Event('input')); // fixing it clears the mark at once
    expect($('vm-create-name').getAttribute('aria-invalid')).toBe('false');
    $('vm-create-next').click();
    expect(m().dataset.vmAt).toBe('2');
    expect(document.activeElement.id).toBe('ram');
    $('vm-create-next').click();
    expect(m().dataset.vmAt).toBe('3');
    expect($('vm-create-submit').hidden).toBe(false);
    expect($('vm-create-next').hidden).toBe(true);
    $('vm-create-back').click();
    expect(m().dataset.vmAt).toBe('2');
  });

  it('keeps to the three steps and copes with a bare dialog', () => {
    expect(showStep(m(), 9)).toBe(3);
    expect(showStep(m(), 0)).toBe(1);
    const bare = document.createElement('div');
    expect(installSteps(bare)).toBe(1);
    expect(checkName(bare)).toBe(false);
  });
});
