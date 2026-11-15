// Backup's controls follow the person's rights (SET-21, Backup B9). A backup manager saw, and was
// refused by: the monthly-check switch, "Connect from a recovery kit", "Bring back everything", the
// two USB ticks, and the settings file's download and upload. Each control names the rights the
// server asks for; without any of them it is hidden with the mark the sidebar uses.
// No imports on purpose: importing route-access.js or hide-marks.js from here split them into
// chunks of their own on the first load and broke its budget (FE-01).

const NO_ACCESS = 'data-no-access'; // hide-marks.js's mark

/** The server's rule, as route-access.js has it: "*", "area:*", exact; "*:read" for reads. */
export function allows(scopes, need) {
  const list = scopes || [];
  if (list.includes('*') || list.includes(need)) return true;
  const [area, verb] = need.split(':');
  if (verb && list.includes(`${area}:*`)) return true;
  return (verb === 'read' || verb === 'view') && list.includes('*:read');
}

/** @type {Array<[string, string[]]>} [selector, any of these rights] as the routes ask. */
export const NEEDS = [
  ['[data-off="connect"]', ['*']],
  ['[data-off="everything"]', ['*']],
  ['[data-rd="all"]', ['*']],
  ['[data-off-usb]', ['system:config']],
  ['#btn-backup-download', ['*']],
  ['.bk-upload', ['*']],
  ['[data-scrub-pool]', ['storage:admin']],
];

/** Marks what this account can't use; nothing while the account isn't known yet. */
export function applyNeeds(root, user = /** @type {any} */ (globalThis).kibotoUser) {
  if (!root || !user) return 0;
  let hidden = 0;
  for (const [sel, rights] of NEEDS) {
    const allowed = rights.some((r) => allows(user.scopes, r));
    root.querySelectorAll(sel).forEach((node) => {
      const el = /** @type {HTMLElement} */ (node);
      if (!allowed) {
        el.setAttribute(NO_ACCESS, '');
        el.hidden = true;
        hidden += 1;
      } else if (el.hasAttribute(NO_ACCESS)) {
        el.removeAttribute(NO_ACCESS);
        el.hidden = false;
      }
    });
  }
  return hidden;
}
