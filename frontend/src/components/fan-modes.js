/**
 * The fan modes in words, shared by the Host tab and the Fans tab (SET-15, Hardware 1). Quiet,
 * Balanced and Performance follow the hottest drive on a curve (backend/hardware/fans.py:
 * PRESET_CURVES; Hardware 1 Part B), Custom ("auto") follows the person's own points. Only Full
 * and a speed set by hand are fixed: they do not follow the temperature, so choosing one asks first.
 */
import { t } from '../i18n.js';
import { showConfirmToast } from '../toast.js';

/** What each fixed mode runs at, in percent of full speed. */
export const FIXED_PCT = { full: 100 };

/** A mode's name: "Automatic", "Quiet · fixed 37 %", "Fixed 50 %" (set by hand). */
export function modeName(profile, manualPct) {
  const p = String(profile || '').toLowerCase();
  if (p === 'auto') return t('fan.mode_custom', 'Custom');
  if (p === 'quiet') return t('fan.mode_quiet', 'Quiet');
  if (p === 'balanced') return t('fan.mode_balanced', 'Balanced');
  if (p === 'performance') return t('fan.mode_performance', 'Performance');
  if (p === 'full') return t('hw.mode_full', 'Full speed');
  const pct = Number(manualPct);
  return Number.isFinite(pct)
    ? t('hw.mode_manual', 'Fixed {pct} %', { pct: Math.round(pct) })
    : t('hw.mode_manual_any', 'Set by hand');
}

/** Asks before the fans run at a fixed speed; onYes runs only on a yes, onNo otherwise. */
export function askFixedSpeed(pct, onYes, onNo = null) {
  showConfirmToast(
    t('fan.fixed_title', 'Keep the fans at a fixed {pct} %?', { pct }),
    t(
      'fan.fixed_msg',
      'At a fixed speed the fans do not follow the temperature. They speed up only when a drive reaches 55 °C or the processor gets very hot. Automatic follows the temperature and is recommended.'
    ),
    onYes,
    onNo,
    { okText: t('fan.fixed_ok', 'Use {pct} %', { pct }), cancelText: t('common.cancel', 'Cancel') }
  );
}
