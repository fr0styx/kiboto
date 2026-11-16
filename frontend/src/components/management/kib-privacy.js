// Kib settings → Privacy (SET-26, AI 4; report section 4, section 3): a short list built from the
// real settings. The first line is fixed; then one line for each thing that is on: web lookups, and
// each address that is not this NAS, with what is sent there.
import { escapeHtml } from '../../utils.js';
import { t } from '../../i18n.js';

/** The settings that send something to a server, and what they send. @type {Array<[string, () => string]>} */
const SENDS = [
  ['llm_endpoint', () => t('kibp.chat', 'questions and the parts of files that answer them, for the chat model')],
  ['embedding_host', () => t('kibp.reader', 'text from your files, to turn it into search vectors')],
  ['rerank_endpoint', () => t('kibp.rerank', 'search questions and the best results, for a second check')],
  ['photo_vector_host', () => t('kibp.photos', 'small copies of your photos, to find them by what is in them')],
  ['transcribe_endpoint', () => t('kibp.speech', 'audio from voice memos (and videos, if chosen), to turn it into text')],
];

/** True for an address on this NAS: itself, or one of Kiboto's own containers. */
export function onThisNas(url) {
  let host;
  try {
    host = new URL(String(url)).hostname.toLowerCase();
  } catch {
    return false;
  }
  return host === 'localhost' || host === '::1' || host === '[::1]' || host.startsWith('127.') || host.startsWith('kiboto') || host === 'host.docker.internal';
}

/**
 * The list's lines: web lookups always, then each address that is not this NAS.
 * @param {Record<string, any>} cfg Kib's settings (GET /api/ai/config)
 * @returns {string[]}
 */
/** The "On this NAS" line: are chats and the index encrypted (AI decision 11)? */
export function atRestLine(state) {
  if (state === 'encrypted') return t('kibp.enc_on', 'On this NAS: chats and the index are encrypted.');
  if (state === 'encrypting') return t('kibp.enc_going', 'On this NAS: chats and the index are being encrypted.');
  if (state === 'locked') return t('kibp.enc_locked', 'On this NAS: chats and the index are encrypted, but the key is missing or wrong, so Kib cannot open them.');
  if (state === 'off') return t('kibp.enc_off', 'On this NAS: chats and the index are not encrypted. Set KIBOTO_DATA_KEY in the container settings to encrypt them.');
  return '';
}

export function privacyLines(cfg = {}) {
  const lines = [t('kibp.web', 'Web lookups: off unless a chat turns them on; that choice is not remembered.')];
  for (const [key, what] of SENDS) {
    const url = String(cfg[key] || '').trim();
    if (!url || onThisNas(url)) continue;
    let host = url;
    try { host = new URL(url).host; } catch { /* shown as typed */ }
    lines.push(t('kibp.leaves', '{host} gets: {what}.', { host, what: what() }));
  }
  const atRest = atRestLine(cfg.at_rest);
  if (atRest) lines.push(atRest);
  return lines;
}

/** Fills the list. */
export function renderKibPrivacy(listEl, cfg) {
  if (!listEl) return;
  listEl.innerHTML = privacyLines(cfg).map((l) => `<li>${escapeHtml(l)}</li>`).join('');
}
