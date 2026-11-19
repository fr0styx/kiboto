// Activity -> History: "Save as a file" (re-audit R3). The list on screen becomes a CSV file in the
// reader's language; Sign-ins come from the server, which has the whole security log.
import { api } from '../api.js';
import { t } from '../i18n.js';
import { formatDateTime } from '../format.js';
import { showToast } from '../toast.js';

/** One CSV cell: quoted when it must be, and never a formula a spreadsheet would run. */
export function csvCell(value) {
  let s = String(value ?? '');
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** The entries as CSV, as the list shows them (view gives each entry's title and message). */
export function eventsCsv(events, view) {
  const head = [
    t('act.csv_when', 'When'),
    t('act.csv_what', 'What happened'),
    t('act.csv_details', 'Details'),
    t('act.csv_times', 'Times'),
  ];
  const rows = (events || []).map((e) => {
    const v = view(e);
    return [formatDateTime((e.last_ts || e.ts) * 1000), v.title, v.message, e.count || 1];
  });
  return [head, ...rows].map((r) => r.map(csvCell).join(',')).join('\r\n') + '\r\n';
}

export function saveText(name, text) {
  const blob = new Blob(['﻿', text], { type: 'text/csv;charset=utf-8' }); // the mark tells Excel it is UTF-8
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

const today = () => new Date().toISOString().slice(0, 10);

/** Saves what the History list shows: the events on screen, or the whole security log for Sign-ins. */
export async function exportHistory({ filter = 'all', events = [], view }) {
  try {
    if (filter === 'signins') {
      await api.downloadBlob('/api/auth/audit/export', `kiboto-security-log-${today()}.csv`);
    } else {
      saveText(`kiboto-history-${today()}.csv`, eventsCsv(events, view));
    }
    return true;
  } catch (e) {
    showToast(t('act.export_failed', "The list couldn't be saved: {error}", { error: e?.message || '' }), 'error');
    return false;
  }
}
