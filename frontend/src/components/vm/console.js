// The VM console: VNC and serial clients, keyboard, paste, reconnect, and what it says while connecting.
// Part of vm-manager.js, split out by ARC-5.

import { api } from '../../api.js';
import { escapeHtml, copyText } from '../../utils.js';
import { showToast, showPromptToast, showBottomSheet } from '../../toast.js';
import { t } from '../../i18n.js';
import { makeDraggable, bringToFront } from '../dock.js';
import { createTerminalView } from '../terminal-view.js';
import { vmState } from './state.js';
import { isCompact, isTouch } from '../../device.js';
import { setIconLabel } from '../../ui/primitives.js';

// An icon next to translated words: screen readers skip it (UX-35)
const ico = (e) => `<span aria-hidden="true">${e}</span>`;

const CONSOLE_STATUS = {
  live: ['vcon.st_live', 'Live', 'ok'],
  connecting: ['vcon.st_connecting', 'Connecting…', 'warn'],
  reconnecting: ['vcon.st_reconnecting', 'Reconnecting ({s} s)…', 'warn'],
  disconnected: ['vcon.st_disconnected', 'Disconnected', 'crit'],
  tty_connecting: ['vcon.st_tty_connecting', 'Terminal connecting…', 'warn'],
  tty_live: ['vcon.st_tty_live', 'Terminal live', 'ok'],
  tty_closed: ['vcon.st_tty_closed', 'Terminal closed', 'crit'],
  tty_error: ['vcon.st_tty_error', 'Terminal error', 'crit'],
};

/** Shows the console's connection state in the title bar pill, in words and colour. */
export function setConsoleStatus(pill, kind, params) {
  if (!pill) return;
  const [key, words, tone] = CONSOLE_STATUS[kind];
  pill.textContent = `● ${t(key, words, params)}`;
  pill.style.color = `var(--kb-text-${tone})`;
}

/**
 * Universal Clipboard Helper
 * Robust copy support with modern Clipboard API and fallback to execCommand('copy')
 * for non-secure HTTP local IP environments.
 */
export async function copyToClipboard(text) {
  if (!text) return false;

  // 1. Try modern Async Clipboard API in secure context (HTTPS/localhost)
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await copyText(text);
      return true;
    } catch (err) {
      console.warn('Async Clipboard API failed, falling back:', err);
    }
  }

  // 2. Reliable textarea fallback for non-secure HTTP contexts
  try {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.top = '-9999px';
    textArea.style.left = '-9999px';
    textArea.style.opacity = '0';
    textArea.setAttribute('readonly', '');
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    const successful = document.execCommand('copy');
    document.body.removeChild(textArea);
    return successful;
  } catch (err) {
    console.error('execCommand copy fallback failed:', err);
    return false;
  }
}

/**
 * Sets keyboard capture focus state on VM console window
 */
export function setConsoleFocus(focused) {
  const consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin) return;
  consoleWin.dataset.focused = focused ? 'true' : 'false';
  const pill = consoleWin.querySelector('#vm-console-kbd-pill');
  if (pill) {
    if (focused) {
      setIconLabel(pill, '⌨️', t('ui.captured', 'Captured'));
      pill.style.color = '#4fd8c4';
      pill.style.borderColor = 'rgba(51, 205, 184, 0.4)';
      pill.setAttribute('title', t('ui.keyboard_captured_by_vm_console', 'Keyboard captured by VM console. Click outside or minimize to release.'));
    } else {
      setIconLabel(pill, '⌨️', t('ui.click_to_capture', 'Click to capture'));
      pill.style.color = 'var(--muted)';
      pill.style.borderColor = 'rgba(255, 255, 255, 0.1)';
      pill.setAttribute('title', t('vcon.kbd_released', 'Keyboard released to the desktop. Click the console to capture it.'));
    }
  }
}

/**
 * What the console shows until the real screen or serial console is there, or when it can't be
 * opened. It drew a made-up desktop and a fake shell with invented boot lines and command answers
 * before every connection and after a failed one; now it says what is happening (honesty fix).
 */
function paintConsoleNote(canvas, line1, line2 = '') {
  if (!canvas) return;
  for (const k of ['_blinkInterval', '_guiInterval']) {
    if (canvas[k]) {
      clearInterval(canvas[k]);
      canvas[k] = null;
    }
  }
  canvas.dataset.note = line1;
  canvas.setAttribute('aria-label', line2 ? `${line1} ${line2}` : line1);
  // keys pressed here go nowhere, and must not reach the page's own shortcuts either
  canvas.onkeydown = (e) => e.stopPropagation();
  const ctx = typeof canvas.getContext === 'function' ? canvas.getContext('2d') : null;
  if (!ctx) return;
  const w = canvas.width || 800;
  const h = canvas.height || 500;
  ctx.fillStyle = '#0b1416';
  ctx.fillRect(0, 0, w, h);
  ctx.textAlign = 'center';
  ctx.fillStyle = '#d4e2e2';
  ctx.font = '600 16px system-ui, sans-serif';
  ctx.fillText(line1, w / 2, h / 2 - (line2 ? 10 : 0));
  if (line2) {
    ctx.fillStyle = '#8aa3a4';
    ctx.font = '13px system-ui, sans-serif';
    ctx.fillText(line2.slice(0, 120), w / 2, h / 2 + 16);
  }
}

function connectingNote(canvas, vmName, mode) {
  paintConsoleNote(canvas, mode === 'cli'
    ? t('vcon.connecting_cli', 'Connecting to the serial console of {name}…', { name: vmName })
    : t('vcon.connecting_gui', 'Connecting to the screen of {name}…', { name: vmName }));
}

export function failedNote(canvas, vmName, mode, reason = '') {
  const head = mode === 'cli'
    ? t('vcon.failed_cli', 'The serial console of {name} could not be opened.', { name: vmName })
    : t('vcon.failed_gui', 'The screen of {name} could not be opened.', { name: vmName });
  paintConsoleNote(canvas, head, reason || t('vcon.failed_hint', 'Check that the machine is running, then press Reconnect.'));
  showConsoleBanner('error', head);
}

export let _activeRfb = null;
export let _activeSerialWs = null;
export let _reconnectTimer = null;
export const _serialBuffers = new Map(); // keyed by VM id; a Map, so an id can't reach Object's own properties
let _serialView = null;
let _serialViewVmId = null;
const SERIAL_TRANSCRIPT_MAX = 256 * 1024;

// Key -> serial byte sequence, used when a key is typed while the terminal
// itself does not have focus (the console window's global key guard).
export function serialKeyToData(e) {
  const map = {
    Enter: '\r',
    Backspace: '\x7f',
    Tab: '\t',
    Escape: '\x1b',
    ArrowUp: '\x1b[A',
    ArrowDown: '\x1b[B',
    ArrowRight: '\x1b[C',
    ArrowLeft: '\x1b[D',
    Home: '\x1b[H',
    End: '\x1b[F',
    PageUp: '\x1b[5~',
    PageDown: '\x1b[6~',
    Delete: '\x1b[3~',
  };
  if (map[e.key]) return map[e.key];
  if (e.ctrlKey && e.key && e.key.length === 1) {
    const code = e.key.toLowerCase().charCodeAt(0) - 96;
    return code >= 1 && code <= 26 ? String.fromCharCode(code) : null;
  }
  if (e.key && e.key.length === 1 && !e.metaKey && !e.altKey) return e.key;
  return null;
}

function rememberSerialChunk(vmId, chunk) {
  let list = _serialBuffers.get(vmId);
  if (!list) _serialBuffers.set(vmId, (list = []));
  list.push(chunk);
  let total = list.reduce((n, c) => n + (c.length || c.byteLength || 0), 0);
  while (total > SERIAL_TRANSCRIPT_MAX && list.length > 1) {
    const old = list.shift();
    total -= old.length || old.byteLength || 0;
  }
}

function ensureSerialView(host, vmId) {
  if (!host) return null;
  const intact = host.querySelector('.zt-terminal-fallback, .zt-terminal-xterm');
  if (_serialView && _serialView.host === host && _serialViewVmId === vmId && intact) return _serialView;
  if (_serialView) _serialView.dispose();
  _serialView = createTerminalView(host, {
    theme: { background: '#0b1517', cursorAccent: '#0b1517' },
    onData: (d) => {
      if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) _activeSerialWs.send(d);
    },
  });
  _serialViewVmId = vmId;
  // Replay this VM's earlier output so a reconnect keeps the screen history.
  for (const chunk of _serialBuffers.get(vmId) || []) _serialView.write(chunk);
  return _serialView;
}

export function _sendKeyToRfb(keysym, code) {
  if (_activeRfb && typeof _activeRfb.sendKey === 'function') {
    _activeRfb.sendKey(keysym, code, true);
    setTimeout(() => {
      try {
        if (_activeRfb && typeof _activeRfb.sendKey === 'function') {
          _activeRfb.sendKey(keysym, code, false);
        }
      } catch (_) {}
    }, 40);
  }
}

export function _sendCtrlCToRfb() {
  if (_activeRfb && typeof _activeRfb.sendKey === 'function') {
    _activeRfb.sendKey(0xffe3, 'ControlLeft', true);
    _activeRfb.sendKey(0x63, 'KeyC', true);
    setTimeout(() => {
      try {
        if (_activeRfb && typeof _activeRfb.sendKey === 'function') {
          _activeRfb.sendKey(0x63, 'KeyC', false);
          _activeRfb.sendKey(0xffe3, 'ControlLeft', false);
        }
      } catch (_) {}
    }, 40);
  }
}

export function getActiveConsoleTarget(consoleWin) {
  if (!consoleWin) consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin) return null;

  const mode = consoleWin._activeMode || 'gui';
  if (mode === 'gui') {
    const realCanvas = consoleWin.querySelector('.vnc-screen-target canvas');
    if (realCanvas && realCanvas.style.display !== 'none') {
      return realCanvas;
    }
    const simCanvas = consoleWin.querySelector('#vm-console-canvas');
    if (simCanvas && simCanvas.style.display !== 'none') {
      return simCanvas;
    }
    return realCanvas || consoleWin.querySelector('.vnc-screen-target') || consoleWin.querySelector('#vm-console-viewport');
  } else {
    const cliContainer = consoleWin.querySelector('#vm-cli-container');
    if (cliContainer && cliContainer.style.display !== 'none') {
      return cliContainer;
    }
    const simCanvas = consoleWin.querySelector('#vm-console-canvas');
    if (simCanvas && simCanvas.style.display !== 'none') {
      return simCanvas;
    }
    return cliContainer;
  }
}

export function focusActiveConsole() {
  const consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin) return;
  const mode = consoleWin._activeMode || 'gui';

  if (mode === 'gui') {
    if (_activeRfb && typeof _activeRfb.focus === 'function') {
      try { _activeRfb.focus({ preventScroll: true }); } catch (_) {}
    }
    const realCanvas = consoleWin.querySelector('.vnc-screen-target canvas');
    if (realCanvas && realCanvas.style.display !== 'none') {
      realCanvas.tabIndex = 0;
      try { realCanvas.focus({ preventScroll: true }); } catch (_) {}
      return;
    }
    const simCanvas = consoleWin.querySelector('#vm-console-canvas');
    if (simCanvas && simCanvas.style.display !== 'none') {
      try { simCanvas.focus({ preventScroll: true }); } catch (_) {}
    }
  } else {
    if (_serialView && _serialView.term) {
      _serialView.focus();
      return;
    }
    const cliContainer = consoleWin.querySelector('#vm-cli-container');
    if (cliContainer) {
      cliContainer.tabIndex = 0;
      try { cliContainer.focus({ preventScroll: true }); } catch (_) {}
    }
  }
}

export function _handleRfbKeyFallback(e) {
  if (!_activeRfb) return;

  const keyMap = {
    'Enter': { keysym: 0xff0d, code: 'Enter' },
    'Backspace': { keysym: 0xff08, code: 'Backspace' },
    'Tab': { keysym: 0xff09, code: 'Tab' },
    'Escape': { keysym: 0xff1b, code: 'Escape' },
    'Delete': { keysym: 0xffff, code: 'Delete' },
    'Insert': { keysym: 0xff63, code: 'Insert' },
    'ArrowUp': { keysym: 0xff52, code: 'ArrowUp' },
    'ArrowDown': { keysym: 0xff54, code: 'ArrowDown' },
    'ArrowLeft': { keysym: 0xff51, code: 'ArrowLeft' },
    'ArrowRight': { keysym: 0xff53, code: 'ArrowRight' },
    'Home': { keysym: 0xff50, code: 'Home' },
    'End': { keysym: 0xff57, code: 'End' },
    'PageUp': { keysym: 0xff55, code: 'PageUp' },
    'PageDown': { keysym: 0xff56, code: 'PageDown' },
    ' ': { keysym: 0x0020, code: 'Space' },
    'Space': { keysym: 0x0020, code: 'Space' },
    'F1': { keysym: 0xffbe, code: 'F1' },
    'F2': { keysym: 0xffbf, code: 'F2' },
    'F3': { keysym: 0xffc0, code: 'F3' },
    'F4': { keysym: 0xffc1, code: 'F4' },
    'F5': { keysym: 0xffc2, code: 'F5' },
    'F6': { keysym: 0xffc3, code: 'F6' },
    'F7': { keysym: 0xffc4, code: 'F7' },
    'F8': { keysym: 0xffc5, code: 'F8' },
    'F9': { keysym: 0xffc6, code: 'F9' },
    'F10': { keysym: 0xffc7, code: 'F10' },
    'F11': { keysym: 0xffc8, code: 'F11' },
    'F12': { keysym: 0xffcb, code: 'F12' },
  };

  if (keyMap[e.key]) {
    e.preventDefault();
    e.stopPropagation();
    _sendKeyToRfb(keyMap[e.key].keysym, keyMap[e.key].code);
    return;
  }

  // Ctrl combos
  if (e.ctrlKey && e.key && e.key.length === 1) {
    e.preventDefault();
    e.stopPropagation();
    if (e.key.toLowerCase() === 'c') {
      _sendCtrlCToRfb();
    } else {
      const code = e.code || `Key${e.key.toUpperCase()}`;
      _activeRfb.sendKey?.(0xffe3, 'ControlLeft', true);
      _activeRfb.sendKey?.(e.key.charCodeAt(0), code, true);
      setTimeout(() => {
        try {
          _activeRfb.sendKey?.(e.key.charCodeAt(0), code, false);
          _activeRfb.sendKey?.(0xffe3, 'ControlLeft', false);
        } catch (_) {}
      }, 40);
    }
    return;
  }

  // Single printable characters (letters, digits, symbols)
  if (e.key && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault();
    e.stopPropagation();
    const keysym = e.key.charCodeAt(0);
    const code = e.code || null;
    _sendKeyToRfb(keysym, code);
  }
}

export let _consoleReconnectAttempts = 0;

export function showConsoleBanner(type = 'connecting', message = '', actions = []) {
  const banner = document.getElementById('vm-console-banner');
  if (!banner) return;

  banner.className = `vm-console-banner banner-${type}`;
  let iconSvg;
  if (type === 'connecting') {
    iconSvg = `<svg class="spin-clockwise" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></svg>`;
  } else if (type === 'connected') {
    iconSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`;
  } else if (type === 'disconnected') {
    iconSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
  } else {
    iconSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
  }

  let actionsHtml = '';
  if (actions && actions.length > 0) {
    actionsHtml = `<div class="banner-actions">` +
      actions.map((act, idx) => `<button class="btn-banner-act ${act.primary ? 'primary' : 'secondary'}" data-act-idx="${idx}">${escapeHtml(act.label)}</button>`).join('') +
      `</div>`;
  }

  banner.innerHTML = `
    <div class="banner-content">
      ${iconSvg}
      <span class="banner-text">${escapeHtml(message)}</span>
    </div>
    ${actionsHtml}
  `;
  banner.style.display = 'flex';

  if (actions && actions.length > 0) {
    banner.querySelectorAll('.btn-banner-act').forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.actIdx, 10);
        if (actions[idx]?.onClick) actions[idx].onClick();
      };
    });
  }

  if (type === 'connected') {
    if (banner._fadeTimeout) clearTimeout(banner._fadeTimeout);
    banner._fadeTimeout = setTimeout(() => {
      hideConsoleBanner();
    }, 3500);
  }
}

export function hideConsoleBanner() {
  const banner = document.getElementById('vm-console-banner');
  if (banner) {
    if (banner._fadeTimeout) clearTimeout(banner._fadeTimeout);
    banner.style.display = 'none';
  }
}

export function cancelConsoleReconnect() {
  if (_reconnectTimer) {
    clearTimeout(_reconnectTimer);
    _reconnectTimer = null;
  }
  hideConsoleBanner();
}

export const clearConsoleReconnectTimer = cancelConsoleReconnect;

export function _scheduleConsoleReconnect(container, vmId, vmName, mode) {
  cancelConsoleReconnect();
  const consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin || consoleWin.style.display === 'none' || consoleWin.classList.contains('window-minimized') || consoleWin._userClosing) {
    return;
  }

  if (_consoleReconnectAttempts >= 5) {
    const statusPill = document.getElementById('vm-console-status-pill');
    setConsoleStatus(statusPill, 'disconnected');
    showConsoleBanner('disconnected', t('vcon.gave_up', 'Lost the connection to {name} after 5 tries.', { name: vmName }), [
      {
        label: t('vcon.reconnect_now', 'Reconnect now'),
        primary: true,
        onClick: () => {
          _consoleReconnectAttempts = 0;
          _scheduleConsoleReconnect(container, vmId, vmName, mode);
        },
      },
    ]);
    return;
  }

  const statusPill = document.getElementById('vm-console-status-pill');
  let countdown = 5;
  setConsoleStatus(statusPill, 'reconnecting', { s: countdown });

  const triggerNow = () => {
    cancelConsoleReconnect();
    _consoleReconnectAttempts++;
    setConsoleStatus(statusPill, 'connecting');
    showConsoleBanner('connecting', t('vcon.reconnecting_to', 'Reconnecting to {name} (try {n} of 5)…', { name: vmName, n: _consoleReconnectAttempts }));
    const win = document.getElementById('vm-console-window');
    if (mode === 'gui') {
      const vncWrap = win ? win.querySelector('#vm-vnc-container') : container;
      initRealVncClient(vncWrap, vmId, vmName);
    } else {
      const cliWrap = win ? win.querySelector('#vm-cli-container') : container;
      initRealSerialTerminal(cliWrap, vmId, vmName);
    }
  };

  const cancelRec = () => {
    cancelConsoleReconnect();
    setConsoleStatus(statusPill, 'disconnected');
    showConsoleBanner('disconnected', t('vcon.disconnected', 'Disconnected from the VM console'), [
      {
        label: t('vcon.reconnect_now', 'Reconnect now'),
        primary: true,
        onClick: () => {
          _consoleReconnectAttempts = 0;
          triggerNow();
        },
      },
    ]);
  };

  showConsoleBanner('disconnected', t('vcon.lost', 'Connection lost. Reconnecting in {s} s (try {n} of 5)…', { s: countdown, n: _consoleReconnectAttempts + 1 }), [
    { label: t('vcon.reconnect_now', 'Reconnect now'), primary: true, onClick: triggerNow },
    { label: t('common.cancel', 'Cancel'), primary: false, onClick: cancelRec },
  ]);

  const tick = () => {
    countdown--;
    const win = document.getElementById('vm-console-window');
    if (!win || win.style.display === 'none' || win.classList.contains('window-minimized') || win._userClosing) {
      cancelConsoleReconnect();
      return;
    }
    if (countdown > 0) {
      setConsoleStatus(statusPill, 'reconnecting', { s: countdown });
      const banner = document.getElementById('vm-console-banner');
      const txt = banner?.querySelector('.banner-text');
      if (txt) {
        txt.textContent = t('vcon.lost', 'Connection lost. Reconnecting in {s} s (try {n} of 5)…', { s: countdown, n: _consoleReconnectAttempts + 1 });
      }
      _reconnectTimer = setTimeout(tick, 1000);
    } else {
      _reconnectTimer = null;
      triggerNow();
    }
  };
  _reconnectTimer = setTimeout(tick, 1000);
}

/**
 * Universal paste helper to forward text characters into guest console or serial socket.
 */
export async function pasteTextToGuestConsole(text) {
  if (!text) return;
  const consoleWin = document.getElementById('vm-console-window');
  const mode = consoleWin?._activeMode || 'gui';
  if (mode === 'gui') {
    if (_activeRfb) {
      if (typeof _activeRfb.clipboardPasteFrom === 'function') {
        try {
          _activeRfb.clipboardPasteFrom(text);
        } catch (_) {}
      }
      for (let i = 0; i < text.length; i++) {
        const ch = text[i];
        if (ch === '\r') continue;
        if (ch === '\n') {
          _sendKeyToRfb(0xff0d, 'Enter');
        } else if (ch === '\t') {
          _sendKeyToRfb(0xff09, 'Tab');
        } else {
          _sendKeyToRfb(ch.charCodeAt(0), null);
        }
        if (text.length > 1) {
          await new Promise((r) => setTimeout(r, 15));
        }
      }
      showToast(t('toast.pasted_characters_into_guest_vm', 'Pasted {count} characters into guest VM', { count: text.length }), 'success');
    } else {
      showToast(t('toast.pasted_characters_into_guest_input_stream', 'Pasted {count} characters into guest input stream', { count: text.length }), 'success');
    }
  } else {
    if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) {
      _activeSerialWs.send(text.replace(/\r?\n/g, '\r'));
      showToast(t('toast.sent_characters_to_serial_terminal', 'Sent {count} characters to serial terminal', { count: text.length }), 'success');
    } else {
      showToast(t('toast.sent_characters_to_terminal', 'Sent {count} characters to terminal', { count: text.length }), 'success');
    }
  }
}

async function initRealVncClient(container, vmId, vmName) {
  cancelConsoleReconnect();
  if (_activeRfb) {
    try { _activeRfb.disconnect(); } catch (_) {}
    _activeRfb = null;
  }
  const statusPill = document.getElementById('vm-console-status-pill');
  setConsoleStatus(statusPill, 'connecting');

  try {
    let tokenRes = null;
    try {
      tokenRes = await api.post(`/api/vms/${vmId}/console/token`);
    } catch (e) {
      console.warn('[VM Console] Ticket request failed:', e);
    }
    const ticket = tokenRes?.ticket || '';
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host || '127.0.0.1:8082';
    const wsUrl = `${protocol}//${host}/api/vms/${vmId}/console/ws?ticket=${ticket}`;

    let RFB = null;
    try {
      const mod = await import('@novnc/novnc');
      RFB = mod.default || mod;
    } catch (e) {
      console.warn('[VM Console] noVNC library load notice:', e);
    }

    if (RFB && container && typeof window !== 'undefined' && window.WebSocket) {
      let vncScreen = container.querySelector('.vnc-screen-target');
      if (!vncScreen) {
        vncScreen = document.createElement('div');
        vncScreen.className = 'vnc-screen-target';
        vncScreen.style.cssText = 'width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;';
        container.appendChild(vncScreen);
      } else {
        vncScreen.innerHTML = '';
      }

      const canvas = container.querySelector('#vm-console-canvas');
      if (canvas) canvas.style.display = 'none';

      const rfb = new RFB(vncScreen, wsUrl, {
        credentials: { password: '' },
        wsProtocols: ['binary'],
      });
      rfb.scaleViewport = true;
      rfb.resizeSession = false;
      rfb.clipViewport = false;
      rfb.focusOnClick = true;

      rfb.addEventListener('connect', () => {
        setConsoleStatus(statusPill, 'live');
        const resStat = document.getElementById('vm-console-resolution-stat');
        if (resStat && rfb._fbWidth) {
          resStat.textContent = `${rfb._fbWidth} × ${rfb._fbHeight}`;
        }
        showToast(t('toast.connected_to_display', 'Connected to {vmName} display', { vmName: vmName }), 'success');

        const realCanvas = vncScreen.querySelector('canvas');
        if (realCanvas) {
          realCanvas.tabIndex = 0;
          realCanvas.style.outline = 'none';
          try { realCanvas.focus({ preventScroll: true }); } catch (_) {}
          realCanvas.addEventListener('focus', () => setConsoleFocus(true));
        }
        try { rfb.focus({ preventScroll: true }); } catch (_) {}
        setConsoleFocus(true);
      });

      vncScreen.addEventListener('mousedown', () => {
        setConsoleFocus(true);
        const realCanvas = vncScreen.querySelector('canvas');
        if (realCanvas) {
          realCanvas.tabIndex = 0;
          try { realCanvas.focus({ preventScroll: true }); } catch (_) {}
        }
        try { rfb.focus({ preventScroll: true }); } catch (_) {}
      });

      rfb.addEventListener('disconnect', (e) => {
        setConsoleStatus(statusPill, 'disconnected');
        if (e && e.detail && !e.detail.clean) {
          showToast(t('toast.console_disconnected', 'Console disconnected: {reason}', { reason: e.detail.reason || 'Connection closed' }), 'warning');
        }
        const consoleWin = document.getElementById('vm-console-window');
        if (consoleWin && !consoleWin._userClosing) {
          _scheduleConsoleReconnect(container, vmId, vmName, 'gui');
        }
      });

      rfb.addEventListener('securityfailure', (e) => {
        showToast(t('toast.vnc_security_error', 'VNC security error: {reason}', { reason: e.detail?.reason || t('toast.authentication_failed', 'Authentication failed') }), 'error');
      });

      _activeRfb = rfb;
      return rfb;
    }
  } catch (err) {
    console.warn('[VM Console] VNC client error:', err);
  }

  // the screen could not be opened: say so (it drew a made-up desktop here)
  const canvas = container ? container.querySelector('#vm-console-canvas') : null;
  if (canvas) {
    canvas.style.display = 'block';
    failedNote(canvas, vmName, 'gui');
  }
}

async function initRealSerialTerminal(container, vmId, vmName) {
  cancelConsoleReconnect();
  if (_activeSerialWs) {
    try { _activeSerialWs.close(); } catch (_) {}
    _activeSerialWs = null;
  }
  const statusPill = document.getElementById('vm-console-status-pill');
  setConsoleStatus(statusPill, 'tty_connecting');

  const host = container ? container.querySelector('#vm-cli-output') : null;
  const view = ensureSerialView(host, vmId);
  const appendOutput = (chunk) => {
    rememberSerialChunk(vmId, chunk);
    if (view) view.write(chunk);
  };
  if (!(_serialBuffers.get(vmId) || []).length) {
    appendOutput(`\x1b[36m[Kiboto Serial Terminal - Connecting to ${vmName}...]\x1b[0m\r\n`);
  }

  try {
    let tokenRes = null;
    try {
      tokenRes = await api.post(`/api/vms/${vmId}/console/token`);
    } catch (e) {}
    const ticket = tokenRes?.ticket || '';
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = window.location.host || '127.0.0.1:8082';
    const wsUrl = `${protocol}//${wsHost}/api/vms/${encodeURIComponent(vmId)}/serial/ws?ticket=${encodeURIComponent(ticket)}`;

    if (typeof WebSocket !== 'undefined') {
      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';
      ws.onopen = () => {
        setConsoleStatus(statusPill, 'tty_live');
        appendOutput(`\x1b[32m[Connected to serial console. Press Enter if screen is blank.]\x1b[0m\r\n\r\n`);
        if (view) view.focus();
        else container?.focus();
      };
      ws.onmessage = (e) => {
        if (e.data) appendOutput(typeof e.data === 'string' ? e.data : new Uint8Array(e.data));
      };
      ws.onclose = () => {
        setConsoleStatus(statusPill, 'tty_closed');
        appendOutput(`\r\n\x1b[31m[Serial connection closed]\x1b[0m\r\n`);
        const consoleWin = document.getElementById('vm-console-window');
        if (consoleWin && !consoleWin._userClosing) {
          _scheduleConsoleReconnect(container, vmId, vmName, 'cli');
        }
      };
      ws.onerror = () => {
        setConsoleStatus(statusPill, 'tty_error');
      };

      if (container) {
        container.tabIndex = 0;
        // Keys typed inside xterm never reach here (the view stops them); this
        // only handles keys forwarded by the console window's key guard.
        container.onkeydown = (e) => {
          e.stopPropagation();
          const data = serialKeyToData(e);
          if (data && ws.readyState === WebSocket.OPEN) {
            e.preventDefault();
            ws.send(data);
            if (view) view.focus();
          }
        };
      }

      _activeSerialWs = ws;
      return;
    }
  } catch (err) {
    console.warn('[VM Console] Serial terminal error:', err);
  }

  // the serial console could not be opened: say so (it ran a fake shell here)
  const canvas = document.getElementById('vm-console-canvas');
  if (canvas) {
    canvas.style.display = 'block';
    failedNote(canvas, vmName, 'cli');
  }
}


/**
 * Opens the dedicated glassmorphic VM Console Window (#vm-console-window)
 */
export function openVmConsole(vmId, vmName = 'Virtual Machine', initialMode = 'gui') {
  let consoleWin = document.getElementById('vm-console-window');
  if (!consoleWin) {
    const html = `
      <div id="vm-console-window" class="os-window vm-console-window" data-focused="true" style="display: none; width: 880px; height: 600px; min-width: 640px; min-height: 480px;">
        <div class="os-window-header" id="vm-console-header">
          <div class="os-window-title" style="display: flex; align-items: center; gap: 8px;">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            <span id="vm-console-title-text">${escapeHtml(t('vcon.title', 'VM Console: {name}', { name: vmName }))}</span>
            <span id="vm-console-status-pill" class="console-status-pill">● ${t('vcon.st_live', 'Live')}</span>
          </div>
          <div class="os-window-controls">
            <button class="win-btn min-btn" id="vm-console-min" title="${t('window.minimize', 'Minimize')}" aria-label="${t('window.minimize', 'Minimize')}"></button>
            <button class="win-btn max-btn" id="vm-console-max" title="${t('ui.maximize', 'Maximize')}" aria-label="${t('ui.maximize', 'Maximize')}"></button>
            <button class="win-btn close-btn" id="vm-console-close" title="${t('diagnostics.close_btn', 'Close')}" aria-label="${t('diagnostics.close_btn', 'Close')}"></button>
          </div>
        </div>

        <!-- Console Control Bar -->
        <div class="vm-console-toolbar">
          <div class="console-toolbar-left">
            <div class="console-mode-switch">
              <button class="btn-console-mode ${initialMode === 'gui' ? 'active' : ''}" id="btn-console-mode-gui" title="${t('vm.mode_gui', 'KVM GUI')}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                <span>${t('vm.mode_gui', 'KVM GUI')}</span>
              </button>
              <button class="btn-console-mode ${initialMode === 'cli' ? 'active' : ''}" id="btn-console-mode-cli" title="${t('vm.mode_tty', 'Serial TTY')}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                <span>${t('vm.mode_tty', 'Serial TTY')}</span>
              </button>
            </div>
            <span class="toolbar-stat"><span class="stat-dot-pulse"></span> 60 FPS</span>
            <span class="toolbar-stat" id="vm-console-resolution-stat">${initialMode === 'cli' ? '80 × 25 TTY' : '1920 × 1080'}</span>
            <span class="toolbar-stat" id="vm-console-adapter-stat" style="color: ${initialMode === 'cli' ? '#34d399' : '#4fd8c4'};">${initialMode === 'cli' ? 'Serial TTY' : 'VirtIO-GPU'}</span>
            <span class="toolbar-stat" id="vm-console-kbd-pill" style="color: var(--kb-text-accent); font-weight: 500; cursor: pointer;" title="${t('ui.keyboard_captured_by_vm_console', 'Keyboard captured by VM console. Click outside or minimize to release.')}"><span aria-hidden="true">⌨️</span> ${t('ui.captured', 'Captured')}</span>
          </div>
          <div class="console-toolbar-right">
            <button class="btn-console-act" id="btn-vnc-softkbd" title="${t('vm.soft_kbd', 'Keyboard')}">
              <span>⌨️ ${t('vm.soft_kbd', 'Keyboard')}</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-cad" title="${t('ui.send_ctrl_alt_del', 'Send Ctrl+Alt+Del')}">
              <span translate="no">Ctrl+Alt+Del</span>
            </button>
            <div class="dropdown-sendkey-wrap" style="position: relative;">
              <button class="btn-console-act" id="btn-vnc-keys" title="${t('ui.send_special_key', 'Send Special Key')}">
                <span>${t('vcon.send_key', 'Send key')} ${ico('▾')}</span>
              </button>
              <div id="menu-vnc-keys" class="vnc-keys-menu" style="display: none;">
                <button class="vnc-key-item" data-key="Tab" translate="no">Tab</button>
                <button class="vnc-key-item" data-key="Escape" translate="no">Escape</button>
                <button class="vnc-key-item" data-key="Ctrl+C" translate="no">Ctrl + C</button>
                <button class="vnc-key-item" data-key="Super">${t('vcon.super', 'Super / Windows key')}</button>
                <button class="vnc-key-item" data-key="F12">${t('vcon.f12', 'F12 (boot menu)')}</button>
              </div>
            </div>
            <button class="btn-console-act" id="btn-vnc-clipboard" title="${t('ui.paste_text_to_guest', 'Paste text to guest')}">
              <span>${ico('📋')} ${t('vcon.paste', 'Paste text')}</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-popout" title="${t('vm.popout', 'Separate Window')}">
              <span>↗ ${t('vm.popout', 'Separate Window')}</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-reconnect" title="${t('ui.reconnect_stream', 'Reconnect stream')}">
              <span>${ico('↻')} ${t('vcon.reconnect', 'Reconnect')}</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-fullscreen" title="${t('ctx.fullscreen', 'Toggle Fullscreen')}">
              <span>${ico('⛶')} ${t('vcon.fullscreen', 'Full screen')}</span>
            </button>
          </div>
        </div>

        <!-- Viewport -->
        <div class="vm-console-viewport" id="vm-console-viewport" style="position: relative; flex: 1; display: flex; align-items: center; justify-content: center; background: var(--lt-b-071011ff, #071011); overflow: hidden;">
          <div id="vm-console-banner" class="vm-console-banner" style="display: none;"></div>
          <input type="text" id="vm-console-hidden-input" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" tabindex="-1" style="position: absolute; opacity: 0; pointer-events: none; width: 1px; height: 1px; left: 0; top: 0; z-index: -1;" />
          <div id="vm-vnc-container" style="width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; overflow: hidden;">
            <canvas id="vm-console-canvas" tabindex="0" width="880" height="510"></canvas>
          </div>
          <div id="vm-cli-container" tabindex="0" style="width: 100%; height: 100%; display: none; background: var(--lt-b-0b1517ff, #0b1517); padding: 10px 8px 10px 12px; color: var(--kb-text-ok); overflow: hidden; box-sizing: border-box; outline: none;">
            <div id="vm-cli-output" style="width: 100%; height: 100%;"></div>
          </div>
          <div class="console-scanlines" style="pointer-events: none;"></div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
    consoleWin = document.getElementById('vm-console-window');

    // Register with DockManager
    if (window.DockManager) {
      window.DockManager.register('vm-console', consoleWin, '#i-vm', `Console: ${vmName}`);
    }

    makeDraggable(consoleWin, consoleWin.querySelector('#vm-console-header'));
    consoleWin.addEventListener('mousedown', (e) => {
      bringToFront(consoleWin);
      setConsoleFocus(true);
      const tag = e.target?.tagName?.toLowerCase();
      if (['button', 'input', 'select', 'textarea'].includes(tag) || e.target?.closest?.('button, input, select, textarea, .dropdown-sendkey-wrap, .os-window-controls')) {
        return;
      }
      focusActiveConsole();
    });

    document.addEventListener('mousedown', (e) => {
      const cw = document.getElementById('vm-console-window');
      if (cw && !cw.contains(e.target)) {
        setConsoleFocus(false);
      }
    });

    const kbdPill = consoleWin.querySelector('#vm-console-kbd-pill');
    if (kbdPill) {
      kbdPill.onclick = (e) => {
        e.stopPropagation();
        bringToFront(consoleWin);
        setConsoleFocus(true);
        focusActiveConsole();
        const hiddenInput = consoleWin.querySelector('#vm-console-hidden-input');
        if (hiddenInput && isTouch()) {
          hiddenInput.focus();
        }
      };
    }

    const viewport = consoleWin.querySelector('#vm-console-viewport');
    if (viewport) {
      viewport.addEventListener('click', (e) => {
        const tag = e.target?.tagName?.toLowerCase();
        if (['button', 'input', 'select', 'textarea'].includes(tag) || e.target?.closest?.('button, input, select, textarea')) {
          return;
        }
        setConsoleFocus(true);
        focusActiveConsole();
      });
    }

    const hiddenInput = consoleWin.querySelector('#vm-console-hidden-input');
    const btnSoftKbd = consoleWin.querySelector('#btn-vnc-softkbd');
    if (btnSoftKbd && hiddenInput) {
      btnSoftKbd.onclick = (e) => {
        e.stopPropagation();
        bringToFront(consoleWin);
        setConsoleFocus(true);
        hiddenInput.focus();
      };
    }
    if (hiddenInput) {
      hiddenInput.addEventListener('input', () => {
        const val = hiddenInput.value;
        if (val) {
          const mode = consoleWin._activeMode || 'gui';
          if (mode === 'gui') {
            for (let i = 0; i < val.length; i++) {
              const ch = val[i];
              if (ch === '\n') _sendKeyToRfb(0xff0d, 'Enter');
              else _sendKeyToRfb(ch.charCodeAt(0), null);
            }
          } else if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) {
            _activeSerialWs.send(val.replace(/\r?\n/g, '\r'));
          }
          hiddenInput.value = '';
        }
      });
      hiddenInput.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace') {
          const mode = consoleWin._activeMode || 'gui';
          if (mode === 'gui') {
            _sendKeyToRfb(0xff08, 'Backspace');
          } else if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) {
            e.preventDefault();
            e.stopPropagation();
            _activeSerialWs.send('\x7f');
          }
        } else if (e.key === 'Enter') {
          const mode = consoleWin._activeMode || 'gui';
          if (mode === 'gui') {
            _sendKeyToRfb(0xff0d, 'Enter');
          } else if (_activeSerialWs && _activeSerialWs.readyState === WebSocket.OPEN) {
            e.preventDefault();
            e.stopPropagation();
            _activeSerialWs.send('\r');
          }
        }
      });
    }

    // Minimize, Maximize, Close Bindings
    const minBtn = consoleWin.querySelector('#vm-console-min');
    const maxBtn = consoleWin.querySelector('#vm-console-max');
    const closeBtn = consoleWin.querySelector('#vm-console-close');

    if (minBtn) {
      minBtn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        cancelConsoleReconnect();
        setConsoleFocus(false);
        consoleWin.classList.add('window-minimized');
        consoleWin.classList.remove('open');
        consoleWin.style.setProperty('display', 'none', 'important');
        if (window.DockManager) window.DockManager.minimize('vm-console');
      };
    }
    if (closeBtn) {
      closeBtn.onclick = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        consoleWin._userClosing = true;
        cancelConsoleReconnect();
        setConsoleFocus(false);
        if (_activeRfb) {
          try { _activeRfb.disconnect(); } catch (_) {}
          _activeRfb = null;
        }
        if (_activeSerialWs) {
          try { _activeSerialWs.close(); } catch (_) {}
          _activeSerialWs = null;
        }
        const canvas = consoleWin.querySelector('#vm-console-canvas');
        if (canvas && canvas._blinkInterval) {
          clearInterval(canvas._blinkInterval);
          canvas._blinkInterval = null;
        }
        if (document.body.classList.contains('vm-console-direct')) {
          try {
            window.close();
          } catch (_) {}
          document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:var(--lt-b-071011ff, #071011);color:var(--kb-text-muted);font-family:sans-serif;font-size:14px;">' + escapeHtml(t('vmc.disconnected_close', 'Console disconnected. You can close this window.')) + '</div>';
          return;
        }
        consoleWin.classList.add('window-minimized');
        consoleWin.classList.remove('open');
        consoleWin.style.setProperty('display', 'none', 'important');
        if (window.DockManager) {
          window.DockManager.closeWindow('vm-console');
        }
      };
    }
    let isMax = false;
    let preBounds = null;
    if (maxBtn) {
      maxBtn.onclick = () => {
        if (!isMax) {
          preBounds = {
            left: consoleWin.style.left,
            top: consoleWin.style.top,
            width: consoleWin.style.width,
            height: consoleWin.style.height,
          };
          consoleWin.style.left = '0px';
          consoleWin.style.top = '36px';
          consoleWin.style.width = '100vw';
          consoleWin.style.height = 'calc(100vh - 36px - 72px)';
          isMax = true;
        } else {
          if (preBounds) {
            consoleWin.style.left = preBounds.left;
            consoleWin.style.top = preBounds.top;
            consoleWin.style.width = preBounds.width;
            consoleWin.style.height = preBounds.height;
          }
          isMax = false;
        }
      };
    }

    // Key dropdown toggle
    const btnKeys = consoleWin.querySelector('#btn-vnc-keys');
    const menuKeys = consoleWin.querySelector('#menu-vnc-keys');
    if (btnKeys && menuKeys) {
      btnKeys.onclick = (e) => {
        e.stopPropagation();
        const isMobile = isCompact();
        if (isMobile) {
          showBottomSheet({
            title: t('ui.send_special_key', 'Send Special Key'),
            subtitle: consoleWin._vmName || vmName,
            items: [
              { icon: '⇥', label: 'Tab', onClick: () => { _sendKeyToRfb(0xff09, 'Tab'); showToast(t('toast.sent_key_tab_to_guest_vm', "Sent key 'Tab' to guest VM"), 'info'); } },
              { icon: '⎋', label: 'Escape', onClick: () => { _sendKeyToRfb(0xff1b, 'Escape'); showToast(t('toast.sent_key_escape_to_guest_vm', "Sent key 'Escape' to guest VM"), 'info'); } },
              { icon: '🛑', label: 'Ctrl + C', onClick: () => { _sendCtrlCToRfb(); showToast(t('toast.sent_key_ctrl_c_to_guest', "Sent key 'Ctrl+C' to guest VM"), 'info'); } },
              { icon: '🪟', label: t('vcon.super', 'Super / Windows key'), onClick: () => { _sendKeyToRfb(0xffeb, 'MetaLeft'); showToast(t('toast.sent_key_super_to_guest_vm', "Sent key 'Super' to guest VM"), 'info'); } },
              { icon: '⚙️', label: t('vcon.f12', 'F12 (boot menu)'), onClick: () => { _sendKeyToRfb(0xffcb, 'F12'); showToast(t('toast.sent_key_f12_to_guest_vm', "Sent key 'F12' to guest VM"), 'info'); } },
              // text installers need the arrows and Enter, which a phone keyboard lacks (VMs report 34)
              { icon: '↑', label: t('vcon.k_up', 'Up arrow'), onClick: () => _sendKeyToRfb(0xff52, 'ArrowUp') },
              { icon: '↓', label: t('vcon.k_down', 'Down arrow'), onClick: () => _sendKeyToRfb(0xff54, 'ArrowDown') },
              { icon: '←', label: t('vcon.k_left', 'Left arrow'), onClick: () => _sendKeyToRfb(0xff51, 'ArrowLeft') },
              { icon: '→', label: t('vcon.k_right', 'Right arrow'), onClick: () => _sendKeyToRfb(0xff53, 'ArrowRight') },
              { icon: '⏎', label: t('vcon.k_enter', 'Enter'), onClick: () => _sendKeyToRfb(0xff0d, 'Enter') },
              { icon: '⚡', label: 'Ctrl + Alt + Del', destructive: true, onClick: () => { consoleWin.querySelector('#btn-vnc-cad')?.click(); } },
            ],
          });
          return;
        }
        menuKeys.style.display = menuKeys.style.display === 'none' ? 'block' : 'none';
      };
      consoleWin.querySelectorAll('.vnc-key-item').forEach((item) => {
        item.onclick = (e) => {
          e.stopPropagation();
          const key = item.dataset.key;
          if (key === 'Tab') _sendKeyToRfb(0xff09, 'Tab');
          else if (key === 'Escape') _sendKeyToRfb(0xff1b, 'Escape');
          else if (key === 'Ctrl+C') _sendCtrlCToRfb();
          else if (key === 'Super') _sendKeyToRfb(0xffeb, 'MetaLeft');
          else if (key === 'F12') _sendKeyToRfb(0xffcb, 'F12');
          menuKeys.style.display = 'none';
          showToast(t('toast.sent_key_to_guest_vm', 'Sent key \'{key}\' to guest VM', { key: key }), 'info');
        };
      });
      document.addEventListener('click', () => {
        if (menuKeys) menuKeys.style.display = 'none';
      });
    }

    // Ctrl+Alt+Del
    const btnCad = consoleWin.querySelector('#btn-vnc-cad');
    if (btnCad) {
      btnCad.onclick = () => {
        if (_activeRfb && typeof _activeRfb.sendCtrlAltDel === 'function') {
          _activeRfb.sendCtrlAltDel();
        }
        showToast(t('toast.sent_ctrl_alt_del_signal_to', 'Sent Ctrl+Alt+Del signal to {vmName}', { vmName: consoleWin._vmName || vmName }), 'info');
      };
    }

    // Fullscreen
    const btnFs = consoleWin.querySelector('#btn-vnc-fullscreen');
    if (btnFs && viewport) {
      btnFs.onclick = () => {
        if (!document.fullscreenElement) {
          viewport.requestFullscreen?.().catch(() => {});
        } else {
          document.exitFullscreen?.().catch(() => {});
        }
      };
    }

    // Mode Switcher Buttons
    const btnModeGui = consoleWin.querySelector('#btn-console-mode-gui');
    const btnModeCli = consoleWin.querySelector('#btn-console-mode-cli');

    if (btnModeGui) {
      btnModeGui.onclick = () => {
        setConsoleMode('gui');
      };
    }
    if (btnModeCli) {
      btnModeCli.onclick = () => {
        setConsoleMode('cli');
      };
    }

    // Reconnect
    const btnRec = consoleWin.querySelector('#btn-vnc-reconnect');
    if (btnRec) {
      btnRec.onclick = () => {
        showToast(t('toast.reconnecting_console_stream', 'Reconnecting console stream...'), 'info');
        const mode = consoleWin._activeMode || 'gui';
        if (mode === 'gui') {
          const vncWrap = consoleWin.querySelector('#vm-vnc-container');
          initRealVncClient(vncWrap, consoleWin._vmId || vmId, consoleWin._vmName || vmName);
        } else {
          const cliWrap = consoleWin.querySelector('#vm-cli-container');
          initRealSerialTerminal(cliWrap, consoleWin._vmId || vmId, consoleWin._vmName || vmName);
        }
      };
    }

    // Native window paste event
    consoleWin.addEventListener('paste', async (e) => {
      const activeEl = document.activeElement;
      if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA') && activeEl.id !== 'vm-console-hidden-input') {
        return;
      }
      e.preventDefault();
      const text = e.clipboardData?.getData('text') || '';
      if (text) {
        await pasteTextToGuestConsole(text);
      }
    });

    // Clipboard paste prompt
    const btnClip = consoleWin.querySelector('#btn-vnc-clipboard');
    if (btnClip) {
      btnClip.onclick = async () => {
        let text = '';
        try {
          if (navigator.clipboard && navigator.clipboard.readText) {
            text = await navigator.clipboard.readText();
          }
        } catch (_) {}
        if (text) {
          await pasteTextToGuestConsole(text);
        } else {
          showPromptToast(
            t('vm.paste_modal_title', 'Paste Text to Guest VM'),
            t('vm.paste_modal_desc', 'Enter or paste the text string to send to the virtual machine console:'),
            '',
            async (val) => {
              if (val) {
                await pasteTextToGuestConsole(val);
              }
            },
            null,
            {
              inputType: 'textarea',
              icon: '📋',
              okText: t('vm.paste_btn_action', 'Paste into VM'),
              placeholder: t('vm.paste_placeholder', 'Type or paste commands, keys, or text here... (Ctrl+Enter to send)'),
            }
          );
        }
      };
    }

    // Pop out in separate window
    const btnPopout = consoleWin.querySelector('#btn-vnc-popout');
    if (btnPopout) {
      btnPopout.onclick = () => {
        const curId = consoleWin._vmId || vmId;
        const curName = consoleWin._vmName || vmName;
        const curMode = consoleWin._activeMode || 'gui';
        openVmConsoleSeparateWindow(curId, curName, curMode);
        if (closeBtn) closeBtn.click();
      };
    }
  }

  function setConsoleMode(mode) {
    consoleWin._activeMode = mode;
    const btnGui = consoleWin.querySelector('#btn-console-mode-gui');
    const btnCli = consoleWin.querySelector('#btn-console-mode-cli');
    const resStat = consoleWin.querySelector('#vm-console-resolution-stat');
    const adpStat = consoleWin.querySelector('#vm-console-adapter-stat');
    const titleTxt = consoleWin.querySelector('#vm-console-title-text');

    const vncWrap = consoleWin.querySelector('#vm-vnc-container');
    const cliWrap = consoleWin.querySelector('#vm-cli-container');

    const canvas = consoleWin.querySelector('#vm-console-canvas');

    if (mode === 'gui') {
      if (btnGui) btnGui.classList.add('active');
      if (btnCli) btnCli.classList.remove('active');
      if (resStat) resStat.textContent = '1920 × 1080';
      if (adpStat) {
        adpStat.textContent = t('vm.display_virtio_gpu', 'VirtIO-GPU');
        adpStat.style.color = '#4fd8c4';
      }
      if (titleTxt) titleTxt.textContent = t('vcon.title_mode', 'VM Console: {name} ({mode})', { name: consoleWin._vmName || vmName, mode: t('vm.mode_gui', 'KVM GUI') });

      if (vncWrap) vncWrap.style.display = 'flex';
      if (cliWrap) cliWrap.style.display = 'none';

      if (_activeSerialWs) {
        try { _activeSerialWs.close(); } catch (_) {}
        _activeSerialWs = null;
      }
      if (canvas) {
        connectingNote(canvas, consoleWin._vmName || vmName, 'gui');
      }
      const isTestEnv = typeof window !== 'undefined' && (window.__VITEST__ || window.VITEST);
      if (!isTestEnv) {
        initRealVncClient(vncWrap, consoleWin._vmId || vmId, consoleWin._vmName || vmName);
      }
      focusActiveConsole();
    } else {
      if (btnCli) btnCli.classList.add('active');
      if (btnGui) btnGui.classList.remove('active');
      if (resStat) resStat.textContent = '80 × 25 TTY';
      if (adpStat) {
        adpStat.textContent = t('vm.mode_tty', 'Serial TTY');
        adpStat.style.color = '#34d399';
      }
      if (titleTxt) titleTxt.textContent = t('vcon.title_mode', 'VM Console: {name} ({mode})', { name: consoleWin._vmName || vmName, mode: t('vm.mode_tty', 'Serial TTY') });

      if (vncWrap) vncWrap.style.display = 'none';
      if (cliWrap) cliWrap.style.display = 'block';

      if (_activeRfb) {
        try { _activeRfb.disconnect(); } catch (_) {}
        _activeRfb = null;
      }
      if (canvas) {
        connectingNote(canvas, consoleWin._vmName || vmName, 'cli');
      }
      const isTestEnv = typeof window !== 'undefined' && (window.__VITEST__ || window.VITEST);
      if (!isTestEnv) {
        initRealSerialTerminal(cliWrap, consoleWin._vmId || vmId, consoleWin._vmName || vmName);
      }
      focusActiveConsole();
    }
  }

  consoleWin._setConsoleMode = setConsoleMode;
  consoleWin._vmName = vmName;
  consoleWin._vmId = vmId;
  consoleWin._userClosing = false;
  cancelConsoleReconnect();

  if (window.DockManager) {
    window.DockManager.register('vm-console', consoleWin, '#i-vm', `Console: ${vmName}`);
    window.DockManager.restore('vm-console');
  }
  consoleWin.classList.remove('window-minimized');
  consoleWin.classList.add('open');
  consoleWin.style.removeProperty('display');
  consoleWin.style.setProperty('display', 'flex', 'important');
  bringToFront(consoleWin);

  if (typeof document !== 'undefined' && document.body && document.body.classList.contains('vm-console-direct')) {
    consoleWin.classList.add('vm-console-standalone');
    document.title = `${t('vcon.title', 'VM Console: {name}', { name: vmName })} - Kiboto`;
  }

  setConsoleMode(initialMode || 'gui');
  focusActiveConsole();
}

/**
 * Opens VM Console in a dedicated separate native browser window
 * @param {string} vmId
 * @param {string} vmName
 * @param {string} mode - 'gui' or 'cli'
 */
export function openVmConsoleSeparateWindow(vmId, vmName = 'Virtual Machine', mode = 'gui') {
  const availW = (typeof window !== 'undefined' && window.screen && window.screen.availWidth) ? window.screen.availWidth : 1280;
  const availH = (typeof window !== 'undefined' && window.screen && window.screen.availHeight) ? window.screen.availHeight : 800;
  const width = Math.min(1366, Math.max(960, Math.floor(availW * 0.85)));
  const height = Math.min(900, Math.max(680, Math.floor(availH * 0.85)));
  const left = Math.max(0, Math.floor((availW - width) / 2));
  const top = Math.max(0, Math.floor((availH - height) / 2));
  const origin = (typeof window !== 'undefined' && window.location) ? window.location.origin : '';
  const pathname = (typeof window !== 'undefined' && window.location) ? window.location.pathname : '/';
  const url = `${origin}${pathname}?mode=vm-console&vm=${encodeURIComponent(vmId)}&name=${encodeURIComponent(vmName || '')}&consoleMode=${encodeURIComponent(mode || 'gui')}`;

  if (typeof window !== 'undefined' && window.open) {
    const win = window.open(
      url,
      `vm_console_${vmId}`,
      `width=${width},height=${height},left=${left},top=${top},menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=no`
    );
    if (win && win.focus) {
      try { win.focus(); } catch (_) {}
    }
    return win;
  }
  return null;
}

if (typeof window !== 'undefined') {
  window.openVmConsoleSeparateWindow = openVmConsoleSeparateWindow;
}

// Global Focus Guard for VM Console Keyboard Capture
if (typeof window !== 'undefined' && !window._vmConsoleGlobalCaptureBound) {
  window._vmConsoleGlobalCaptureBound = true;
  window.addEventListener(
    'keydown',
    (e) => {
      const cw = document.getElementById('vm-console-window');
      if (!cw || cw.style.display === 'none' || cw.classList.contains('window-minimized')) {
        return;
      }
      const isFocused = cw.dataset.focused === 'true' || cw.contains(document.activeElement);
      if (!isFocused) return;

      const activeTag = document.activeElement?.tagName?.toLowerCase();
      if (['input', 'textarea', 'select'].includes(activeTag) && document.activeElement?.id !== 'vm-console-hidden-input') {
        return;
      }

      if (e.key === 'Tab') {
        e.preventDefault();
      }

      const mode = cw._activeMode || 'gui';
      if (mode === 'gui') {
        const realCanvas = cw.querySelector('.vnc-screen-target canvas');
        if (realCanvas) {
          if (document.activeElement === realCanvas) {
            return;
          }
          realCanvas.tabIndex = 0;
          try { realCanvas.focus({ preventScroll: true }); } catch (_) {}
          if (_activeRfb && typeof _activeRfb.focus === 'function') {
            try { _activeRfb.focus({ preventScroll: true }); } catch (_) {}
          }
          _handleRfbKeyFallback(e);
          return;
        }

        // Offline / Test Simulation canvas
        const simCanvas = cw.querySelector('#vm-console-canvas');
        if (simCanvas && simCanvas.style.display !== 'none') {
          if (document.activeElement !== simCanvas) {
            simCanvas.focus();
          }
          if (simCanvas.onkeydown && e.target !== simCanvas) {
            simCanvas.onkeydown(e);
          }
        }
      } else {
        // Serial TTY mode
        const cliContainer = cw.querySelector('#vm-cli-container');
        if (cliContainer && cliContainer.style.display !== 'none') {
          if (cliContainer === document.activeElement || cliContainer.contains(e.target)) {
            return;
          }
          try { cliContainer.focus({ preventScroll: true }); } catch (_) {}
          if (cliContainer.onkeydown) {
            e.preventDefault();
            e.stopPropagation();
            cliContainer.onkeydown(e);
          }
          return;
        }
        const simCanvas = cw.querySelector('#vm-console-canvas');
        if (simCanvas && simCanvas.style.display !== 'none') {
          if (document.activeElement === simCanvas || simCanvas.contains(e.target)) {
            return;
          }
          if (simCanvas.onkeydown) {
            e.preventDefault();
            e.stopPropagation();
            simCanvas.onkeydown(e);
          }
        }
      }
    },
    true
  );
}
