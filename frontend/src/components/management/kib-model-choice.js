// "Kib answers with" (SET-26, AI 6; owner's decision 6): Automatic (recommended), or Fast / Balanced /
// Best, each with the model's name small below and how it runs here, measured by "Test speed". No
// model names unless you open the list under it. The choice is kept on the server, so a later speed
// test moves it to the model that now fits.
import { api } from '../../api.js';
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';
import { showToast } from '../../toast.js';

const CHOICES = ['auto', 'fast', 'balanced', 'best'];

/** The words for a choice. */
export function choiceWords(c) {
  return (
    {
      auto: [t('kibm.auto', 'Automatic (recommended)'), t('kibm.auto_2', 'Kiboto picks the model that fits this NAS.')],
      fast: [t('kibm.fast', 'Fast'), t('kibm.fast_2', 'Short answers, quickly.')],
      balanced: [t('kibm.balanced', 'Balanced'), t('kibm.balanced_2', 'Good answers at reading speed.')],
      best: [t('kibm.best', 'Best'), t('kibm.best_2', 'The most careful answers this NAS can give, more slowly.')],
    }[c] || [c, '']
  );
}

/** How a measured model runs here, in words: never a number alone. */
export function fitWords(result) {
  const tps = Number(result?.tokens_per_s || 0);
  if (!result) return '';
  if (tps >= 12) return t('kibm.fit_well', 'runs well here');
  if (tps >= 4) return t('kibm.fit_slower', 'slower here');
  return t('kibm.fit_slow', 'may be slow here');
}

/**
 * The model behind each choice, with its measurement.
 * @param {string} choice
 * @param {any} bench GET /api/ai/models/benchmark
 * @param {string} active the model Kib uses now
 */
export function modelOf(choice, bench, active) {
  const rec = bench?.recommended || {};
  const name = choice === 'auto' ? rec.balanced || active : rec[choice];
  const result = (bench?.results || []).find((r) => r.name === name);
  return { name: name || '', result };
}

/** The radio group as markup. */
export function modelChoiceHtml(bench, cfg) {
  const current = String(cfg?.model_choice || 'auto');
  const tested = Boolean(bench?.finished_at);
  const running = bench?.job?.state === 'running';
  const rows = CHOICES.map((c) => {
    const [title, note] = choiceWords(c);
    const { name, result } = modelOf(c, bench, cfg?.active_model || '');
    const off = c !== 'auto' && !name;
    const fit = fitWords(result);
    const small = name
      ? `${name}${fit ? ` · ${fit}` : ''}`
      : c === 'auto'
        ? ''
        : t('kibm.untested', 'Test the speed first');
    return `<label class="kibm-row${off ? ' is-off' : ''}">
        <input type="radio" name="kib-model-choice" value="${c}"${current === c ? ' checked' : ''}${off ? ' disabled' : ''}>
        <span class="kibm-text"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(note)}</span>${small ? `<small>${escapeHtml(small)}</small>` : ''}</span>
      </label>`;
  }).join('');
  const manual =
    current === 'manual'
      ? `<p class="kib-note">${escapeHtml(t('kibm.manual', 'You picked {model} by name. Choose one above to let Kiboto pick again.', { model: cfg?.active_model || '' }))}</p>`
      : '';
  const test = running
    ? `<p class="kib-note" role="status">${escapeHtml(t('kibm.testing', 'Testing the speed: {done} of {total, plural, one {# model} other {# models}}…', { done: bench.job.done || 0, total: bench.job.total || 0 }))}</p>`
    : `<button type="button" class="btn-pill-toggle is-small" data-kibm-test>${escapeHtml(tested ? t('kibm.retest', 'Test speed again') : t('kibm.test', 'Test speed'))}</button>`;
  return `<h4 class="kib-h">${escapeHtml(t('kibm.title', 'Kib answers with'))}</h4>
    <div class="kibm-list" role="radiogroup" aria-label="${escapeHtml(t('kibm.title', 'Kib answers with'))}">${rows}</div>${manual}${test}`;
}

/**
 * Draws the choice and wires it: a change asks the server, "Test speed" starts the measurement and
 * redraws when it is done.
 * @param {HTMLElement | null} mount
 * @param {{ wait?: (ms: number) => Promise<void> }} [opts]
 */
export async function renderModelChoice(mount, opts = {}) {
  if (!mount) return;
  const wait = opts.wait || ((ms) => new Promise((r) => setTimeout(r, ms)));
  let bench;
  let cfg;
  try {
    [bench, cfg] = await Promise.all([api.get('/api/ai/models/benchmark'), api.get('/api/ai/config')]);
  } catch {
    mount.innerHTML = `<p class="kib-note">${escapeHtml(t('kibm.load_failed', "Kib's model could not be loaded."))}</p>`;
    return;
  }
  mount.innerHTML = modelChoiceHtml(bench, cfg);
  mount.querySelectorAll('input[name="kib-model-choice"]').forEach((el) => {
    const input = /** @type {HTMLInputElement} */ (el);
    input.addEventListener('change', async () => {
      try {
        const res = await api.post('/api/ai/models/benchmark/apply', { tier: input.value });
        showToast(t('kibm.now', 'Kib now answers with {model}.', { model: res?.active_model || '' }), 'success');
      } catch (err) {
        showToast(t('kibm.failed', 'The choice was not saved: {error}', { error: err.message }), 'error');
      }
      await renderModelChoice(mount, opts);
    });
  });
  mount.querySelector('[data-kibm-test]')?.addEventListener('click', async () => {
    try {
      await api.post('/api/ai/models/benchmark');
    } catch (err) {
      showToast(t('kibm.test_failed', 'The speed test did not start: {error}', { error: err.message }), 'error');
      return;
    }
    for (let i = 0; i < 400; i += 1) {
      await renderModelChoice(mount, opts);
      const st = await api.get('/api/ai/models/benchmark').catch(() => null);
      if (st?.job?.state !== 'running') break;
      await wait(3000);
    }
    await renderModelChoice(mount, opts);
  });
}
