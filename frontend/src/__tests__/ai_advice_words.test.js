// Kib's model advice in the reader's language: the server says how each sentence was made (17 Nov).
import { describe, it, expect, afterEach } from 'vitest';
import { fitBadge, activeWord, modelWords } from '../components/management/ai.js';
import { resolveParams, serverSaid } from '../server-text.js';
import { setLanguage } from '../i18n.js';

const ram = (n) => ({ number: n, digits: 1 });

describe("Kib's model advice", () => {
  afterEach(async () => { await setLanguage('en'); });

  it('writes numbers in the reader\'s language', async () => {
    expect(resolveParams({ gb: ram(58.4), n: { number: 12345 } })).toEqual({ gb: '58.4', n: '12,345' });
    await setLanguage('de');
    expect(resolveParams({ gb: ram(58.4), n: { number: 12345, digits: 0 } })).toEqual({ gb: '58,4', n: '12.345' });
  });

  it('a headline made of parts, with a device word of its own', async () => {
    const how = {
      msg_key: 'srv.ai_head_npu',
      params: { tier: { key: 'srv.ai_tier_one', params: { device: { key: 'srv.ai_label_npu', default: 'Onboard NPU' }, ram: ram(16) } } },
    };
    expect(serverSaid({ text: how }, 'NPU (Onboard NPU (16.0 GB RAM))')).toBe('NPU (Onboard NPU (16.0 GB memory))');
    await setLanguage('de');
    expect(serverSaid({ text: how }, '')).toBe('NPU (Integrierte NPU (16,0 GB Arbeitsspeicher))');
  });

  it('fit badges: the server\'s words, its English, or ours', async () => {
    expect(fitBadge({ fit_badge_text: { msg_key: 'srv.ai_badge_fits', params: {} }, fit_status: 'compatible' }, false, false)).toBe('✓ Fits this NAS');
    expect(fitBadge({ fit_badge_text: { msg_key: 'srv.ai_badge_best_npu', params: {} }, fit_status: 'best_match' }, false, true)).toBe('★ Best for the onboard NPU');
    expect(fitBadge({ fit_badge_text: { msg_key: 'srv.ai_badge_no_fit', params: { gb: 96 } }, fit_status: 'insufficient_ram' }, true, false)).toBe("⚠️ Doesn't fit this NAS (96 GB+ memory)");
    expect(fitBadge({ fit_badge_text: { msg_key: 'srv.ai_badge_fits', params: {} }, fit_status: 'new' }, false, false)).toBe('Fits this NAS');
    expect(fitBadge({ fit_badge: '✓ Fits Your Hardware' }, false, false)).toBe('✓ Fits Your Hardware');
    expect(fitBadge({}, true, false)).toBe("⚠️ Doesn't fit this NAS");
    expect(fitBadge({}, false, true)).toBe('★ Recommended');
    expect(fitBadge({}, false, false)).toBe('✓ Fits this NAS');
    expect(activeWord(true)).toBe('⚠️ Active (too big for this NAS)');
    expect(activeWord(false)).toBe('✓ Active');
    await setLanguage('de');
    expect(fitBadge({}, false, true)).toBe('★ Empfohlen');
    expect(activeWord(false)).toBe('✓ Aktiv');
  });

  it('why a model suits, what it is for and where it runs', async () => {
    const m = {
      warning_text: { msg_key: 'srv.ai_warn_no_fit', params: { model: ram(40), host: 64, ram: ram(32) } },
      warning_message: 'Hardware Warning: ...',
      why_recommended_text: { msg_key: 'srv.ai_why_fits', params: { ram: ram(32), model: ram(2) } },
      why_recommended: 'Fits comfortably ...',
      use_case_text: { msg_key: 'srv.ai_role.llama3_2_3b_npu', params: {} },
      use_case: 'Quick conversation and file tagging',
      target_device_text: { msg_key: 'srv.ai_needs_dgpu', params: { gb: 24 } },
      target_device: 'Needs a discrete GPU with 24 GB',
    };
    expect(modelWords(m)).toEqual({
      warning: "Needs about 40.0 GB for the model (64 GB+ memory recommended), more than this NAS's 32.0 GB.",
      why: "Fits in this NAS's 32.0 GB of memory (needs 2.0 GB).",
      useCase: 'Quick conversation and file tagging',
      device: 'Needs a discrete GPU with 24 GB',
    });
    // an older answer without how: its own words; with nothing at all, ours
    expect(modelWords({ fit_reason: 'Too big', target_device: 'CPU' })).toEqual({ warning: 'Too big', why: '', useCase: '', device: 'CPU' });
    expect(modelWords({}).warning).toBe('This model needs more memory than this NAS has.');
    await setLanguage('de');
    expect(modelWords(m).useCase).toBe('Schnelle Unterhaltung und Datei-Schlagwörter');
    expect(modelWords(m).device).toBe('Benötigt eine eigene Grafikkarte mit 24 GB');
  });
});
