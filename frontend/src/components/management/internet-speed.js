// Network: "Test the internet line" (owner, 19 Nov 2026). Off until an administrator turns it on
// under Security -> Checks that use the internet; then it runs only on this button.
import { api } from '../../api.js';
import { t } from '../../i18n.js';
import { formatDateTime } from '../../format.js';
import { speedText } from './speed-test.js';

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

export function internetResultNodes(last) {
  if (!last) return [];
  const dl = el('dl', 'net-dl');
  const row = (label, value) => dl.append(el('dt', '', label), el('dd', '', value));
  row(t('net.inet_down', 'From the internet to the NAS'), speedText(last.down_mbit || 0));
  row(t('net.inet_up', 'From the NAS to the internet'), speedText(last.up_mbit || 0));
  row(t('net.speed_delay', 'Answer time'), t('net.speed_ms', '{value} ms', { value: Math.round(last.answer_ms || 0) }));
  const when = el(
    'p',
    'kb-muted',
    t('net.inet_when', 'Measured {when}.', { when: formatDateTime((last.measured_at || 0) * 1000) })
  );
  return [dl, when];
}

/** Draws the internet part of the speed section: a hint while it is off, else the button and the last result. */
export async function showInternetSpeed(box = document.getElementById('net-internet-speed')) {
  if (!box) return null;
  let view;
  try {
    view = await api.get('/api/network/speedtest/internet');
  } catch {
    box.hidden = true; // someone who may not change the system does not see it
    return null;
  }
  box.hidden = false;
  if (!view.enabled) {
    box.replaceChildren(
      el(
        'p',
        'kb-muted',
        t(
          'net.inet_off',
          'The internet line itself can be tested too. That asks a service outside your home, so it is off: turn it on under Security → Checks that use the internet.'
        )
      )
    );
    return view;
  }
  const button = el('button', 'btn-pill-toggle', t('net.inet_start', 'Test the internet line'));
  button.type = 'button';
  const result = el('div', 'net-home');
  result.setAttribute('role', 'status');
  result.append(...internetResultNodes(view.last));
  box.replaceChildren(button, result);
  button.addEventListener('click', async () => {
    button.disabled = true;
    result.textContent = t('net.inet_running', 'Measuring the internet line… this takes about 20 seconds.');
    try {
      result.replaceChildren(...internetResultNodes(await api.post('/api/network/speedtest/internet', {})));
    } catch (e) {
      result.textContent = t('net.inet_failed', "The internet line couldn't be measured: {error}", {
        error: e?.message || '',
      });
    } finally {
      button.disabled = false;
    }
  });
  return view;
}
