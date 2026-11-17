// "Apply" in the stack editor (Apps decision 4b): first what will happen, service by service, in
// words; then the server applies the file as a job and puts everything back if anything fails.
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast, showConfirmToast } from '../toast.js';

/** One line per service: new, replaced (and why), kept, removed. */
export function stepLines(steps) {
  return (steps || []).map((s) => {
    if (s.action === 'new') return t('stap.new', 'New: {service} ({image})', { service: s.service, image: s.image || '' });
    if (s.action === 'replace') return t('stap.replace', 'Replaced: {service} ({why})', { service: s.service, why: (s.why || []).join(', ') });
    if (s.action === 'remove') return t('stap.remove', 'Removed: {service}', { service: s.service });
    return t('stap.keep', 'Kept as it is: {service}', { service: s.service });
  });
}

/** The question before applying, with the host-level access the file asks for. */
export function applyQuestion(preview) {
  const lines = stepLines(preview.steps);
  const access = (preview.elevated || []).map((e) => t('stap.access', '{service} gets access to the host: {reasons}', { service: e.service, reasons: e.reasons.join(', ') }));
  const tail = t('stap.tail', 'Containers that change are set aside first; if anything does not start, everything goes back as it was.');
  return [...lines, ...access, tail].join('\n');
}

/** Waits for the job to end; resolves {status, error}. */
export async function followJob(id, wait = (ms) => new Promise((r) => setTimeout(r, ms)), tries = 600) {
  for (let i = 0; i < tries; i += 1) {
    let data;
    try {
      data = await api.get('/api/jobs');
    } catch {
      data = null;
    }
    const all = [...(data?.active || []), ...(data?.history || [])];
    const job = all.find((j) => j.id === id);
    if (job && !['running', 'queued', 'pending'].includes(job.status)) return { status: job.status, error: job.error || '' };
    await wait(2000);
  }
  return { status: 'unknown', error: '' };
}

/**
 * Previews, asks, applies and reports.
 * @param {string} name
 * @param {string} compose
 * @param {string} env
 * @param {{ msg?: HTMLElement | null, done?: () => unknown, wait?: (ms: number) => Promise<unknown>, create?: boolean }} [opts]
 */
export async function applyStack(name, compose, env, opts = {}) {
  const say = (text) => { if (opts.msg) opts.msg.textContent = text; };
  let preview;
  try {
    preview = await api.post(`/api/docker/stacks/${encodeURIComponent(name)}/preview`, { compose_yaml: compose, env_content: env });
  } catch (err) {
    say(/** @type {Error} */ (err).message);
    showToast(/** @type {Error} */ (err).message, 'error');
    return false;
  }
  if (!(preview.steps || []).some((s) => s.action !== 'keep')) {
    showToast(t('stap.nothing', 'Nothing to change: the containers already match the file.'), 'info');
    return false;
  }
  const ok = await new Promise((resolve) => {
    showConfirmToast(t('stap.title', 'Apply this file to {name}?', { name }), applyQuestion(preview), () => resolve(true), () => resolve(false), {
      okText: t('stap.ok', 'Apply'),
      isDanger: (preview.elevated || []).length > 0,
    });
  });
  if (!ok) return false;
  let started;
  try {
    // the question above named the host access, so it is the confirmation the server asks for
    const step = opts.create ? 'create' : 'apply'; // a new app's name is checked again by the server
    started = await api.post(`/api/docker/stacks/${encodeURIComponent(name)}/${step}`, { compose_yaml: compose, env_content: env }, { confirmed: true });
  } catch (err) {
    say(/** @type {Error} */ (err).message);
    showToast(/** @type {Error} */ (err).message, 'error');
    return false;
  }
  say(t('stap.running', 'Applying {name}; it shows in Jobs.', { name }));
  showToast(t('stap.running', 'Applying {name}; it shows in Jobs.', { name }), 'info');
  const end = await followJob(started.job, opts.wait);
  if (end.status === 'done') {
    say(t('stap.done', '{name} is applied.', { name }));
    showToast(t('stap.done', '{name} is applied.', { name }), 'success');
    if (opts.done) await opts.done();
    return true;
  }
  const why = end.error || t('stap.unknown', 'Kiboto could not tell how it ended; look in Jobs.');
  say(why);
  showToast(t('stap.failed', '{name} was not applied: {error}', { name, error: why }), 'error');
  return false;
}
