/** AI 6: "Kib answers with" Automatic, Fast, Balanced or Best, with names small and how they run here. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  choiceWords,
  fitWords,
  modelOf,
  modelChoiceHtml,
  renderModelChoice,
} from '../components/management/kib-model-choice.js';
import { loadModelChoice } from '../components/management/ai.js';
import { api } from '../api.js';
import { showToast } from '../toast.js';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showPromptToast: vi.fn(),
  showBottomSheet: vi.fn(),
}));

const BENCH = {
  finished_at: 1,
  recommended: { fast: 'qwen3:1.7b', balanced: 'qwen3:4b', best: 'gemma3:12b' },
  results: [
    { name: 'qwen3:1.7b', tokens_per_s: 40 },
    { name: 'qwen3:4b', tokens_per_s: 15 },
    { name: 'gemma3:12b', tokens_per_s: 5 },
  ],
  job: { state: 'done' },
};
const flush = () => new Promise((r) => setTimeout(r, 0));
const radios = () => [...document.querySelectorAll('input[name="kib-model-choice"]')];

describe('Kib answers with (AI 6)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<section id="kib-model-choice"></section>';
    vi.clearAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());

  it('says each choice and how a model runs here in words', () => {
    expect(choiceWords('auto')[0]).toBe('Automatic (recommended)');
    expect(choiceWords('best')[1]).toBe('The most careful answers this NAS can give, more slowly.');
    expect(choiceWords('odd')).toEqual(['odd', '']);
    expect([
      fitWords({ tokens_per_s: 20 }),
      fitWords({ tokens_per_s: 5 }),
      fitWords({ tokens_per_s: 1 }),
      fitWords(undefined),
    ]).toEqual(['runs well here', 'slower here', 'may be slow here', '']);
    expect(modelOf('auto', BENCH, 'x').name).toBe('qwen3:4b');
    expect(modelOf('auto', {}, 'mine').name).toBe('mine');
    expect(modelOf('best', {}, 'mine').name).toBe('');
  });

  it('before a speed test only Automatic can be chosen', () => {
    document.body.innerHTML = modelChoiceHtml({}, { model_choice: 'auto', active_model: 'qwen3:4b' });
    expect(radios().map((r) => r.disabled)).toEqual([false, true, true, true]);
    expect(document.body.textContent).toContain('Test the speed first');
    expect(document.querySelector('[data-kibm-test]').textContent).toBe('Test speed');
  });

  it('after a test each choice shows its model small, and a named pick says so', () => {
    document.body.innerHTML = modelChoiceHtml(BENCH, { model_choice: 'best', active_model: 'gemma3:12b' });
    expect(radios().find((r) => r.checked).value).toBe('best');
    expect(document.body.textContent).toContain('qwen3:1.7b · runs well here');
    expect(document.body.textContent).toContain('gemma3:12b · slower here');
    expect(document.querySelector('[data-kibm-test]').textContent).toBe('Test speed again');
    document.body.innerHTML = modelChoiceHtml(BENCH, { model_choice: 'manual', active_model: 'llama3' });
    expect(document.body.textContent).toContain('You picked llama3 by name.');
    document.body.innerHTML = modelChoiceHtml({ ...BENCH, job: { state: 'running', done: 1, total: 3 } }, {});
    expect(document.body.textContent).toContain('Testing the speed: 1 of 3 models…');
    expect(document.querySelector('[data-kibm-test]')).toBeNull();
    document.body.innerHTML = modelChoiceHtml({ ...BENCH, job: { state: 'running' } }, {});
    expect(document.body.textContent).toContain('0 of 0 models');
  });

  it('a change asks the server and redraws; a failure says so', async () => {
    const get = vi
      .spyOn(api, 'get')
      .mockImplementation(async (url) =>
        url.includes('benchmark') ? BENCH : { model_choice: 'auto', active_model: 'qwen3:4b' }
      );
    const post = vi
      .spyOn(api, 'post')
      .mockResolvedValueOnce({ active_model: 'qwen3:1.7b' })
      .mockRejectedValueOnce(new Error('denied'))
      .mockResolvedValueOnce(null);
    const mount = document.getElementById('kib-model-choice');
    await renderModelChoice(mount);
    const fast = radios().find((r) => r.value === 'fast');
    fast.checked = true;
    fast.dispatchEvent(new Event('change'));
    await flush();
    await flush();
    expect(post).toHaveBeenCalledWith('/api/ai/models/benchmark/apply', { tier: 'fast' });
    expect(showToast).toHaveBeenCalledWith('Kib now answers with qwen3:1.7b.', 'success');
    const best = radios().find((r) => r.value === 'best');
    best.dispatchEvent(new Event('change'));
    await flush();
    await flush();
    expect(showToast).toHaveBeenLastCalledWith('The choice was not saved: denied', 'error');
    radios()[0].dispatchEvent(new Event('change'));
    await flush();
    await flush();
    expect(showToast).toHaveBeenLastCalledWith('Kib now answers with .', 'success');
    expect(get).toHaveBeenCalled();
  });

  it('Test speed starts the test and waits for it, or says it did not start', async () => {
    let state = 'running';
    vi.spyOn(api, 'get').mockImplementation(async (url) => (url.includes('benchmark') ? { job: { state } } : {}));
    const post = vi.spyOn(api, 'post').mockRejectedValueOnce(new Error('busy')).mockResolvedValue({ started: true });
    const mount = document.getElementById('kib-model-choice');
    const wait = vi.fn(async () => {
      state = 'done';
    });
    await renderModelChoice(mount, { wait });
    document.body.innerHTML = '<section id="kib-model-choice"></section>';
    state = 'done';
    const m2 = document.getElementById('kib-model-choice');
    await renderModelChoice(m2, { wait });
    m2.querySelector('[data-kibm-test]').click();
    await flush();
    expect(showToast).toHaveBeenLastCalledWith('The speed test did not start: busy', 'error');
    state = 'done';
    await renderModelChoice(m2, { wait });
    state = 'running';
    m2.querySelector('[data-kibm-test]').click();
    for (let i = 0; i < 10; i += 1) await flush();
    expect(post).toHaveBeenCalledWith('/api/ai/models/benchmark');
    expect(wait).toHaveBeenCalled();
  });

  it('says when it cannot load, and the page loads it once', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('down'));
    await renderModelChoice(document.getElementById('kib-model-choice'));
    expect(document.body.textContent).toContain("Kib's model could not be loaded.");
    await renderModelChoice(null);
    loadModelChoice();
    loadModelChoice();
    expect(document.getElementById('kib-model-choice').dataset.loaded).toBe('1');
    document.body.innerHTML = '';
    loadModelChoice();
  });
});
