/**
 * A row that scrolls sideways says so. The row gets data-more="end", "start", "both" or "" and
 * the style sheet shows an arrow at the edge where more is hidden (61-touch.css). Kept current
 * while the row scrolls, changes size, or its buttons come and go.
 */

/** Which sides of a row hide more: 'end', 'start', 'both' or ''. */
export function sidesWithMore(row) {
  const max = row.scrollWidth - row.clientWidth;
  if (max <= 4) return '';
  const start = row.scrollLeft > 4;
  const end = max - row.scrollLeft > 4;
  if (start && end) return 'both';
  return end ? 'end' : 'start';
}

/** Watches a row; returns a function that stops watching. A row is watched once. */
export function watchSideScroll(row) {
  if (!row || row.dataset.sideWatch) return () => {};
  row.dataset.sideWatch = '1';
  // a row of buttons carries the arrow as one of its items; anything else (a wide table in a box)
  // gets it laid over its top corner
  if (!String(getComputedStyle(row).display).includes('flex')) row.dataset.moreBlock = '1';
  const say = () => {
    const more = sidesWithMore(row);
    if (row.dataset.more !== more) row.dataset.more = more;
  };
  row.addEventListener('scroll', say, { passive: true });
  const sized = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(say);
  // the row and each thing in it: a button shown by a switch elsewhere on the page changes size,
  // and with it how much there is to scroll, without anything changing in the row itself
  const follow = () => {
    sized?.observe(row);
    for (const child of row.children) sized?.observe(child);
  };
  follow();
  const changed = new MutationObserver(() => {
    follow();
    say();
  });
  changed.observe(row, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ['style', 'class', 'hidden'],
  });
  say();
  return () => {
    row.removeEventListener('scroll', say);
    sized?.disconnect();
    changed.disconnect();
    delete row.dataset.sideWatch;
    delete row.dataset.more;
    delete row.dataset.moreBlock;
  };
}

/** The rows and boxes in Settings that scroll sideways on a narrow screen. */
export const SIDE_SCROLLERS = '.mgmt-inner-tabs, .srep-box, .srep-box-2, #network-vlan-table-wrap, [data-side-scroll]';

/** Watches every such row inside `root`, also those drawn later. Returns a function that stops looking for new ones. */
export function watchSideScrollIn(root, selector = SIDE_SCROLLERS) {
  if (!root) return () => {};
  const look = () => {
    for (const row of root.querySelectorAll(selector)) watchSideScroll(row);
  };
  look();
  const added = new MutationObserver(look);
  added.observe(root, { childList: true, subtree: true });
  return () => added.disconnect();
}
