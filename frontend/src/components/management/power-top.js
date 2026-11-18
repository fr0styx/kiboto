/**
 * The first screen of Power (SET-31, Power stage 3): the status line with up to three numbers, "When
 * the power goes out" and "Will it start again by itself?", all from GET /api/power, so the page,
 * the top bar and Overview say the same thing. Sentences follow the Power report, section 4.
 */
import { t } from '../../i18n.js';
import { escapeHtml } from '../../utils.js';
import { formatDateTime, formatTime } from '../../format.js';
import { serverSaid } from '../../server-text.js';

const ICON = {
  none: '○',
  protected: '✓',
  look: '⚠',
  unreadable: '!',
  cut: '⚡',
  shutting: '⏻',
  by_hand: '✕',
  silent: '?',
};
// the older looks the page's style sheet knows
const LOOK = {
  none: 'none',
  protected: 'mains',
  look: 'look',
  unreadable: 'unreadable',
  silent: 'look',
  cut: 'cut',
  shutting: 'cut',
  by_hand: 'cut',
};
const HOSTS = { unraid: 'Unraid', truenas: 'TrueNAS' };

const minutes = (m) => Math.max(0, Math.round(Number(m)));

/** The word for a state. */
export function powerWord(s) {
  switch (s?.state) {
    case 'protected':
      return t('pwr.w_protected', 'Protected');
    case 'look':
    case 'unreadable':
      return t('overview.word_look', 'Needs a look');
    case 'cut':
      return t('pwr.w_cut', 'The power is out');
    case 'shutting':
      return t('pwr.w_shutting', 'Shutting down');
    case 'by_hand':
      return t('pwr.w_by_hand', 'Shut the NAS down by hand');
    case 'silent':
      return t('pwr.w_silent', 'UPS not answering');
    default:
      return t('pwr.w_none', 'No battery backup');
  }
}

/** The sentence under the word. */
export function powerSentence(s) {
  const n = s?.numbers || {};
  const host = HOSTS[s?.switch_off?.by];
  switch (s?.state) {
    case 'protected':
      if (n.battery_pct != null && n.minutes != null)
        return t(
          'pwr.s_protected',
          'On mains power. The UPS battery is {pct} % full; the UPS estimates about {min} minutes.',
          { pct: Math.round(n.battery_pct), min: minutes(n.minutes) }
        );
      return t('pwr.s_protected_plain', 'On mains power, and the UPS is ready.');
    case 'look':
      if (s.reason === 'switch_off') return t('pwr.s_look_switch', 'Nothing can switch this NAS off in a power cut.');
      if (s.reason === 'battery') {
        return (s.checks || []).some((c) => c.id === 'battery' && c.replace)
          ? t('pwr.s_look_replace', 'The UPS says its battery needs replacing.')
          : t('pwr.s_look_low', 'The UPS battery is low.');
      }
      return t('pwr.s_unreadable', 'A UPS was found, but Kiboto cannot read it.');
    case 'unreadable':
      return s.reason === 'permission'
        ? t(
            'pwr.s_unreadable_usb',
            'A UPS is plugged in by USB, but Kiboto may not open it. The container needs access to the USB device.'
          )
        : t('pwr.s_unreadable', 'A UPS was found, but Kiboto cannot read it.');
    case 'cut': {
      const since = s.since ? formatTime(new Date(s.since * 1000)) : '';
      const head = s.drill
        ? t('pwr.s_drill', 'Practice run: Kiboto acts as if the power were out. Nothing is shut down.')
        : since
          ? t('pwr.s_cut_since', 'Your NAS has been running on the UPS battery since {time}.', { time: since })
          : t('pwr.s_cut', 'Your NAS is running on the UPS battery.');
      const left =
        n.minutes != null
          ? ` ${t('pwr.s_cut_left', 'The UPS estimates about {min} more minutes.', { min: minutes(n.minutes) })}`
          : '';
      const then = host
        ? ` ${t('pwr.s_cut_host', '{host} shuts the NAS down by its own UPS settings, unless the power comes back first.', { host })}`
        : ` ${t('pwr.s_cut_rule', 'Kiboto will shut the NAS down safely when about {min} minutes are left, unless the power comes back first.', { min: s.rule?.minutes ?? 5 })}`;
      return `${head}${left}${then}`;
    }
    case 'shutting':
      return t(
        'pwr.s_shutting',
        'The UPS battery is almost empty. Kiboto is closing your apps and shutting the NAS down now.'
      );
    case 'by_hand':
      return t('pwr.s_by_hand', 'The UPS battery is almost empty and Kiboto cannot switch this NAS off by itself.');
    case 'silent':
      return t('pwr.s_silent', 'Kiboto cannot reach your UPS any more. Check its cable.');
    default:
      return host
        ? t(
            'pwr.s_none_host',
            'Kiboto has not found a UPS (a battery backup). If {host} watches a UPS itself, {host} shuts the NAS down.',
            { host }
          )
        : t(
            'pwr.s_none',
            'Kiboto has not found a UPS (a battery backup). If the power goes out, your NAS switches off at once.'
          );
  }
}

/** Up to three numbers: battery, minutes the UPS estimates, watts (only when the UPS reports its rating). */
export function powerNumbers(s) {
  const n = s?.numbers || {};
  if (!s || ['none', 'unreadable', 'silent'].includes(s.state)) return [];
  const out = [];
  if (n.battery_pct != null) out.push(t('pwr.n_battery', 'Battery {pct} %', { pct: Math.round(n.battery_pct) }));
  if (n.minutes != null) out.push(t('pwr.n_minutes', 'About {min} min', { min: minutes(n.minutes) }));
  if (n.watts != null) out.push(t('pwr.n_watts', '{watts} W in use', { watts: Math.round(n.watts) }));
  return out;
}

/** "When the power goes out": the one line and the numbered steps. */
export function whenPowerGoes(s) {
  const by = s?.switch_off?.by;
  const host = HOSTS[by];
  if (!s || s.state === 'none') {
    return {
      line: t('pwr.when_none', 'Without a battery backup, the NAS switches off at once.'),
      steps: [
        t('pwr.step_none_1', 'Your NAS switches off at once.'),
        t('pwr.step_none_2', 'A file that was being saved at that moment can be damaged.'),
        t('pwr.step_none_3', 'When the power is back, see "Will it start again by itself?" below.'),
      ],
      bad: false,
    };
  }
  const blind = (s.checks || []).some((c) => c.id === 'rule' && c.blind);
  const nobody = !s.switch_off?.ok;
  const last = nobody
    ? t('pwr.step_4_nobody', 'Nothing can switch this NAS off: {why}', {
        why: serverSaid(s.switch_off, s.switch_off?.detail || ''),
      })
    : host
      ? t('pwr.step_4_host', 'Last, {host} switches the NAS off, by its own UPS settings.', { host })
      : t('pwr.step_4', 'Last, Kiboto switches the NAS off.');
  return {
    line: nobody
      ? t('pwr.when_nobody', 'Nothing can switch this NAS off in a power cut.')
      : host
        ? t(
            'pwr.when_host',
            '{host} shuts your NAS down when the battery is nearly empty; Kiboto closes its apps first.',
            { host }
          )
        : t('pwr.when_kiboto', 'Kiboto shuts your NAS down safely when the battery is nearly empty.'),
    steps: [
      t('pwr.step_1', 'The UPS battery takes over at once. Your NAS keeps running and Kiboto shows an alert.'),
      blind
        ? t(
            'pwr.step_2_blind',
            'Kiboto keeps everything running for {min} minutes on battery, because this UPS reports neither its charge nor its time left. If the power comes back before that, nothing is shut down.',
            { min: minutes((s.rule?.timer_sec ?? 300) / 60) }
          )
        : t(
            'pwr.step_2',
            'Kiboto keeps everything running until the battery is nearly empty (about {min} minutes or {pct} % left, or when the UPS itself says so). If the power comes back before that, nothing is shut down.',
            { min: s.rule?.minutes ?? 5, pct: s.rule?.battery_pct ?? 20 }
          ),
      t('pwr.step_3', 'Then Kiboto pauses running copies, closes your apps and saves everything to the drives.'),
      last,
    ],
    bad: nobody,
  };
}

/** What the UPS can do with its sockets after the shutdown, when Kiboto could ask it. */
export function socketsLine(s) {
  const k = s?.sockets;
  if (!k) return '';
  if (k.ok)
    return t(
      'pwr.sockets_ok',
      'Your UPS can switch its sockets back on when the power returns. Turn on the UPS sockets setting below so it does.'
    );
  if (k.code === 'no_command')
    return t('pwr.sockets_no', 'Your UPS has no command to switch its sockets back on when the power returns.');
  return t('pwr.sockets_unknown', 'Kiboto could not ask your UPS whether it switches its sockets back on.');
}

/** "Will it start again by itself?": the answer and its explanation. */
export function comesBack(s) {
  const c = s?.comes_back || { answer: 'not_proven' };
  const sockets = socketsLine(s);
  const why =
    (sockets ? `${sockets} ` : '') +
    t(
      'pwr.back_why',
      'Whether the NAS switches on again when the power returns depends on its own start-up setting (often called "Restore on AC power loss" in the BIOS) and, with a UPS, on whether the UPS switches its sockets back on.'
    );
  if (c.answer === 'ask')
    return {
      line: t('pwr.back_ask', 'After the power cut on {date}: did the NAS switch on again by itself?', {
        date: formatDateTime(c.at * 1000),
      }),
      detail: why,
      ask: true,
    };
  if (c.answer === 'host') return { line: t('pwr.back_host', '{host} decides this.', { host: c.host }), detail: why };
  if (c.answer === 'proven')
    return { line: t('pwr.back_proven', 'Yes, proven on {date}.', { date: formatDateTime(c.at * 1000) }), detail: why };
  if (c.answer === 'no')
    return {
      line: t('pwr.back_no', 'No: after the power cut on {date} the NAS did not start again by itself.', {
        date: formatDateTime(c.at * 1000),
      }),
      detail: why,
    };
  return {
    line: t('pwr.back_unproven', 'Not proven yet.'),
    detail: `${t('pwr.back_how', 'Kiboto marks it proven after a real power cut from which the NAS started again by itself.')} ${why}`,
  };
}

/** The state from a bare reading, for a server from before /api/power. */
export function stateFromReading(ups) {
  if (!ups) return { state: 'none' };
  if (ups.permission_error || ups.unreadable)
    return { state: 'unreadable', reason: ups.permission_error ? 'permission' : '' };
  if (!ups.available) return { state: 'none' };
  if (ups.on_battery) return { state: 'cut', numbers: { minutes: ups.time_left_min } };
  const words = String(ups.status || '')
    .toUpperCase()
    .split(/\s+/);
  if (words.includes('RB'))
    return { state: 'look', reason: 'battery', checks: [{ id: 'battery', ok: false, replace: true }] };
  if (words.includes('LB') || (ups.battery_charge_pct != null && ups.battery_charge_pct <= 20))
    return { state: 'look', reason: 'battery', checks: [] };
  return {
    state: 'protected',
    numbers: { battery_pct: ups.battery_charge_pct, minutes: ups.time_left_min },
    switch_off: { ok: true },
  };
}

/**
 * Draws the first screen into the status box; keeps the reader's open sections open.
 * @param {HTMLElement | null} box
 * @param {any} s the /api/power answer
 * @param {(byItself: boolean) => unknown} [onAnswer] the owner's answer to "did it switch on by itself?"
 */
export function renderPowerTop(box, s, onAnswer) {
  if (!box) return;
  const open = {
    when: box.querySelector('.pw-when')?.hasAttribute('open'),
    back: box.querySelector('.pw-back')?.hasAttribute('open'),
  };
  const state = s?.state || 'none';
  box.dataset.state = LOOK[state] || 'none';
  box.dataset.power = state;
  const when = whenPowerGoes(s);
  const back = comesBack(s);
  const nums = powerNumbers(s);
  box.innerHTML = `
    <div class="ups-status-main"><span id="ups-status-icon" class="ups-status-icon" aria-hidden="true">${ICON[state] || '○'}</span> <strong id="ups-status-word">${escapeHtml(powerWord(s))}</strong></div>
    <div id="ups-status-sentence" class="pw-sentence">${escapeHtml(powerSentence(s))}</div>
    ${nums.length ? `<div class="pw-numbers">${nums.map((x) => `<span class="pw-number">${escapeHtml(x)}</span>`).join('')}</div>` : ''}
    <details class="pw-when${when.bad ? ' is-bad' : ''}"${open.when ? ' open' : ''}><summary><span class="pw-q">${escapeHtml(t('pwr.when_title', 'When the power goes out'))}</span> <span id="ups-shutdown-line" class="pw-a">${escapeHtml(when.line)}</span></summary>
      <ol class="pw-steps">${when.steps.map((x, i) => `<li${when.bad && i === when.steps.length - 1 ? ' class="is-bad"' : ''}>${escapeHtml(x)}</li>`).join('')}</ol></details>
    <details class="pw-back"${open.back || back.ask ? ' open' : ''}><summary><span class="pw-q">${escapeHtml(t('pwr.back_title', 'Will it start again by itself?'))}</span> <span id="ups-restart-line" class="pw-a">${escapeHtml(back.line)}</span></summary>
      <p class="pw-detail">${escapeHtml(back.detail)}</p>${
        back.ask && onAnswer
          ? `<div class="pw-ask">
        <button type="button" class="btn-pill-toggle is-primary" data-back="yes">${escapeHtml(t('pwr.back_yes', 'Yes, by itself'))}</button>
        <button type="button" class="btn-pill-toggle" data-back="no">${escapeHtml(t('pwr.back_no_btn', 'No, someone switched it on'))}</button></div>`
          : ''
      }</details>
    <button type="button" id="ups-show-setup" class="btn-pill-toggle ups-show-setup" hidden>${escapeHtml(t('upx.setup_ups', 'Set up a UPS'))}</button>`;
  box
    .querySelectorAll('[data-back]')
    .forEach((btn) =>
      btn.addEventListener('click', () => onAnswer?.(/** @type {HTMLElement} */ (btn).dataset.back === 'yes'))
    );
}
