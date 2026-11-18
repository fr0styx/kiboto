// Ready-made disks for a new machine (VMs decision 5): Home Assistant OS and other systems that come as
// a .qcow2 disk instead of an installer. The list comes from the installer folders; choosing one makes
// the machine start from its disk.
import { api } from '../../api.js';
import { escapeHtml } from '../../utils.js';

/** Fills the select from the server, keeping a choice already made. */
export async function loadDiskImages(select) {
  if (!select) return [];
  let list;
  try {
    list = await api.get('/api/vms/disk-images');
  } catch {
    list = [];
  }
  const keep = select.value;
  const first = select.options[0] ? select.options[0].outerHTML : '';
  select.innerHTML =
    first +
    (Array.isArray(list) ? list : [])
      .map(
        (d) =>
          `<option value="${escapeHtml(d.path)}">${escapeHtml(d.name)} (${escapeHtml(d.size_formatted || '')})</option>`
      )
      .join('');
  if (keep) select.value = keep;
  return list;
}

/** Wires the field: the list loads, and a chosen disk makes the machine start from its disk. */
export function bindDiskImages(modal) {
  const select = /** @type {HTMLSelectElement | null} */ (modal.querySelector('#vm-create-disk-image'));
  if (!select) return Promise.resolve([]);
  select.addEventListener('change', () => {
    if (!select.value) return;
    const disk = /** @type {HTMLInputElement | null} */ (
      modal.querySelector('input[name="vm-create-boot-order"][value="disk"]')
    );
    if (disk) disk.checked = true;
  });
  return loadDiskImages(select);
}
