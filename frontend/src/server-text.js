// One way to show a text the server sends, in the reader's language (SET-11).
// The server keeps its English sentence and, where it can, adds how the sentence was made:
// `text: { msg_key, params }` on an answer or an error, `details: { title_key, msg_key, params }`
// on an event. Without that the server's own sentence is shown as it came.

import { getLanguage, t } from './i18n.js';
import { formatNumber } from './format.js';

/** Weekday numbers (0 = Monday) as short names in the reader's language. */
export function weekdayNames(days, lang = getLanguage()) {
  const monday = Date.UTC(2024, 0, 1); // a Monday
  let names;
  try {
    const fmt = new Intl.DateTimeFormat(lang || 'en', { weekday: 'short', timeZone: 'UTC' });
    names = (days || []).map((d) => fmt.format(new Date(monday + (Number(d) % 7) * 86400000)));
  } catch (e) {
    names = (days || []).map((d) => ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][Number(d) % 7]);
  }
  return names.join(', ');
}

/** The values of a text: one may be a text to translate ({key, default, params}), weekdays ({weekdays: [0-6]})
 * or a number to write in the reader's language ({number, digits}). */
export function resolveParams(params) {
  const out = {};
  for (const [k, v] of Object.entries(params || {})) {
    if (v && typeof v === 'object' && 'key' in v) out[k] = t(v.key, v.default || '', resolveParams(v.params));
    else if (v && typeof v === 'object' && Array.isArray(v.weekdays)) out[k] = weekdayNames(v.weekdays);
    else if (v && typeof v === 'object' && typeof v.number === 'number') out[k] = numberWords(v);
    else out[k] = v;
  }
  return out;
}

/** A number value of a text, e.g. {number: 12.5, digits: 1} is "12,5" in German. */
function numberWords(v) {
  const digits = v.digits || 0;
  return formatNumber(v.number, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/**
 * The sentence of an answer or an error body, translated when the server said how.
 * @param {any} body
 * @param {string} [fallback] the server's own sentence
 * @returns {string}
 */
export function serverSaid(body, fallback = '') {
  const how = body && typeof body === 'object' ? body.text || body.details : null;
  const own = fallback || (body && (body.detail || body.message)) || '';
  if (how && typeof how === 'object' && how.msg_key) return t(how.msg_key, typeof own === 'string' ? own : '', resolveParams(how.params));
  return typeof own === 'string' ? own : '';
}
