import { describe, it, expect, beforeEach } from 'vitest';
import {
  healthWord,
  poolStatusWord,
  roleWord,
  renderChassisTwin,
  renderStructuredPoolsTopology,
} from '../components/chassis-visualizer.js';
import { setLanguage } from '../i18n.js';

describe('Storage says plain words in your language (SET-22 Storage 1)', () => {
  beforeEach(async () => {
    await setLanguage('en');
  });

  it('one word for health, pool state and role', () => {
    expect(healthWord('PASSED')).toBe('Healthy');
    expect(healthWord('', true)).toBe('Asleep');
    expect(healthWord('failing')).toBe('Failing');
    expect(healthWord('warning')).toBe('Needs a look');
    expect(healthWord('unknown-x')).toBe('unknown-x');
    expect(poolStatusWord(undefined)).toBe('Healthy');
    expect(poolStatusWord('SYNCING')).toBe('Rebuilding protection');
    expect(poolStatusWord('DEGRADED')).toBe('Needs attention');
    expect(poolStatusWord('IMPORTING')).toBe('IMPORTING');
    expect(roleWord('parity')).toBe('Parity');
    expect(roleWord('cache')).toBe('Cache');
    expect(roleWord(undefined)).toBe('Data');
    expect(roleWord('spare')).toBe('SPARE');
  });

  it('the bays have no English capitals left, and German reads German', async () => {
    const box = document.createElement('div');
    const disks = [{ dev: 'sda', model: 'IronWolf', health: 'PASSED', temp: 35, slot: 1 }];
    renderChassisTwin(box, disks, { bays: 4 });
    for (const word of ['VACANT', 'LOCATE', 'EMPTY', 'BAY ']) expect(box.textContent).not.toContain(word);
    await setLanguage('de');
    renderChassisTwin(box, disks, { bays: 4 });
    expect(box.textContent).toContain('Einschub');
    expect(box.textContent).not.toContain('Bay ');
  });

  it('a pool says how full it is in one phrase', () => {
    const box = document.createElement('div');
    renderStructuredPoolsTopology(box, {
      pools: [
        {
          id: 'p',
          name: 'Main',
          fs_type: 'btrfs',
          status: 'DEGRADED',
          used_bytes: 1e12,
          total_bytes: 4e12,
          free_bytes: 3e12,
          used_pct: 25,
          members: [{ device: 'sdb', role: 'parity', size_bytes: 4e12 }],
        },
      ],
    });
    expect(box.textContent).toContain('1.0 TB of 4.0 TB used');
    expect(box.textContent).toContain('Needs attention');
    expect(box.textContent).toContain('Parity');
    expect(box.textContent).not.toContain('used /');
  });

  it("a bay tile shows Drive Health's stored verdict in its words", async () => {
    const { verdictWord } = await import('../components/chassis-visualizer.js');
    expect(verdictWord({ verdict: 'soon', verdict_label_key: 'soon_replace' })).toEqual({
      word: 'Replace soon',
      look: 'warn',
    });
    expect(verdictWord({ verdict: 'ok', verdict_label_key: 'ok' })).toEqual({ word: 'Healthy', look: 'ok' });
    expect(verdictWord({ verdict: 'now', verdict_label_key: 'now_replace' })?.look).toBe('bad');
    expect(verdictWord({})).toBeNull();
    const box = document.createElement('div');
    renderChassisTwin(box, [], {
      chassisConfig: {
        total_bays: 1,
        bays: [
          {
            slot_index: 1,
            is_populated: true,
            disk: {
              dev: 'sda',
              model: 'IronWolf',
              health: 'PASSED',
              temp: 35,
              verdict: 'watch',
              verdict_label_key: 'watch',
            },
          },
        ],
      },
    });
    expect(box.querySelector('.bay-health-tag.is-verdict')?.textContent).toBe('Keep an eye on it');
  });

  it('a bay filled in by guess says the position is not confirmed', () => {
    const box = document.createElement('div');
    const disk = { dev: 'sda', model: 'IronWolf', health: 'PASSED', temp: 35 };
    renderChassisTwin(box, [], {
      chassisConfig: {
        total_bays: 2,
        bays: [
          { slot_index: 1, is_populated: true, mapped: false, disk },
          { slot_index: 2, is_populated: true, mapped: true, disk: { ...disk, dev: 'sdb' } },
        ],
      },
    });
    const notes = box.querySelectorAll('.bay-guess-note');
    expect(notes.length).toBe(1);
    expect(notes[0].textContent).toBe('Position not confirmed');
  });
});
