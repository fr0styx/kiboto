import fs from 'node:fs';
import path from 'node:path';

// A pane of Mission Control as the page has it (src/windows/management-window.html), for tests
// that used to build the Kib panes by hand (SET-26): a test now fails when the real markup loses
// an element the code needs.
const FILE = path.resolve(__dirname, '..', '..', 'windows', 'management-window.html');

/** The outer markup of the element with this id in management-window.html. */
export function windowPane(id) {
  const doc = new DOMParser().parseFromString(`<body>${fs.readFileSync(FILE, 'utf8')}</body>`, 'text/html');
  const el = doc.getElementById(id);
  if (!el) throw new Error(`management-window.html has no #${id}`);
  return el.outerHTML;
}
