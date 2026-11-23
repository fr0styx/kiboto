/**
 * Kib on the desktop: the Kiboto mark as a small character (the display with Kib's eyes, the
 * drive tray and the amber light, docs/BRAND.md) floats in a corner. It bobs, looks around,
 * blinks and now and then hops; pointed at, it perks up. A click opens Kib's own window, without
 * going through Settings. It sits above the desktop icons and below every window; phones have
 * their own launcher and do not show it, and with reduced motion it stays still.
 */
import { t } from '../i18n.js';

const BODY =
  '<svg class="kib-buddy-art" viewBox="0 0 64 74" aria-hidden="true" focusable="false">' +
  '<ellipse class="kib-buddy-shadow" cx="32" cy="69" rx="18" ry="3.5"/>' +
  '<g class="kib-buddy-body"><g transform="translate(-6 -6)">' +
  '<path class="kib-buddy-case" d="M19 6H45A13 13 0 0 1 58 19V37.5A2.5 2.5 0 0 1 55.5 40H8.5A2.5 2.5 0 0 1 6 37.5V19A13 13 0 0 1 19 6ZM8.5 42.5H55.5A2.5 2.5 0 0 1 58 45V45A13 13 0 0 1 45 58H19A13 13 0 0 1 6 45V45A2.5 2.5 0 0 1 8.5 42.5Z"/>' +
  '<path class="kib-buddy-screen" d="M19 13H45A6.5 6.5 0 0 1 51.5 19.5V27A6.5 6.5 0 0 1 45 33.5H19A6.5 6.5 0 0 1 12.5 27V19.5A6.5 6.5 0 0 1 19 13Z"/>' +
  '<g class="kib-buddy-eyes">' +
  '<rect class="kib-buddy-eye" x="21.5" y="17.75" width="6.5" height="11" rx="3.25"/>' +
  '<rect class="kib-buddy-eye" x="36" y="17.75" width="6.5" height="11" rx="3.25"/>' +
  '</g>' +
  '<circle class="kib-buddy-light" cx="49.25" cy="50.25" r="3.2"/>' +
  '</g></g></svg>';

/** Opens Kib's window on its chat. */
export function openKib(win = /** @type {any} */ (window)) {
  win.openKibWindow?.('mgmt-pane-ai-chat');
}

/** Puts Kib on the desktop once; returns the button. */
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
  btn.innerHTML = BODY + '<span class="kib-buddy-label"></span>'; // fixed markup; the label is set as text below
  /** @type {HTMLElement} */ (btn.querySelector('.kib-buddy-label')).textContent = label;
  btn.addEventListener('click', () => {
    btn.classList.remove('is-tapped');
    void btn.offsetWidth; // restart the hop on every click
    btn.classList.add('is-tapped');
    openKib(doc.defaultView);
  });
  btn.addEventListener('animationend', (e) => {
    if (/** @type {AnimationEvent} */ (e).animationName === 'kib-buddy-tap') btn.classList.remove('is-tapped');
  });
  doc.body.appendChild(btn);
  return btn;
}
