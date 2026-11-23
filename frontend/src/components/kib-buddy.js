/**
 * Kib on the desktop: its face (the lit eyes of the brand, docs/BRAND.md) floats in a corner, and a
 * click opens Kib's own window, without going through Settings. It sits above the desktop icons
 * and below every window; phones have their own launcher and do not show it.
 */
import { t } from '../i18n.js';

const FACE = `<svg class="kib-buddy-face" viewBox="0 0 64 36" aria-hidden="true" focusable="false">
  <path d="M11 .75h42A10.25 10.25 0 0 1 63.25 11v14A10.25 10.25 0 0 1 53 35.25H11A10.25 10.25 0 0 1 .75 25V11A10.25 10.25 0 0 1 11 .75Z" class="kib-buddy-tile"/>
  <rect class="kib-buddy-eye" x="19" y="10" width="7.5" height="16" rx="3.75"/>
  <rect class="kib-buddy-eye" x="37.5" y="10" width="7.5" height="16" rx="3.75"/>
</svg>`;

/** Opens Kib's window on its chat. */
export function openKib(win = /** @type {any} */ (window)) {
  win.openKibWindow?.('mgmt-pane-ai-chat');
}

/** Puts Kib's face on the desktop once; returns the button. */
export function initKibBuddy(doc = document) {
  const there = doc.getElementById('kib-buddy');
  if (there) return there;
  const btn = doc.createElement('button');
  btn.type = 'button';
  btn.id = 'kib-buddy';
  btn.className = 'kib-buddy';
  const label = t('dock.kib', 'Ask Kib');
  btn.setAttribute('aria-label', label);
  btn.title = label;
  btn.innerHTML = FACE + '<span class="kib-buddy-label"></span>'; // fixed markup; the label is set as text below
  /** @type {HTMLElement} */ (btn.querySelector('.kib-buddy-label')).textContent = label;
  btn.addEventListener('click', () => openKib(doc.defaultView));
  doc.body.appendChild(btn);
  return btn;
}
