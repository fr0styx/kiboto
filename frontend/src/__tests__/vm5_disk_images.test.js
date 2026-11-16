/** VMs decision 5: ready-made disks (Home Assistant OS) for a new machine. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { loadDiskImages, bindDiskImages } from '../components/vm/disk-images.js';
import { loadIsos } from '../components/vm/isos.js';
import { vmState } from '../components/vm/state.js';
import { api } from '../api.js';

const FORM = '<select id="vm-create-disk-image"><option value="">None</option></select><input type="radio" name="vm-create-boot-order" value="iso" checked><input type="radio" name="vm-create-boot-order" value="disk">';

describe('ready-made disks (VMs decision 5)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('lists the disks from the server and keeps a choice', async () => {
    document.body.innerHTML = FORM;
    vi.spyOn(api, 'get').mockResolvedValueOnce([{ name: 'haos_ova-18.4.qcow2', path: '/i/haos.qcow2', size_formatted: '1.4 GB' }]).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({});
    const sel = document.getElementById('vm-create-disk-image');
    await loadDiskImages(sel);
    expect([...sel.options].map((o) => o.textContent)).toEqual(['None', 'haos_ova-18.4.qcow2 (1.4 GB)']);
    sel.value = '/i/haos.qcow2';
    await loadDiskImages(sel); // offline: the first option stays, the choice is kept if it can be
    expect(sel.options).toHaveLength(1);
    await loadDiskImages(sel);
    expect(await loadDiskImages(null)).toEqual([]);
  });

  it('choosing one makes the machine start from its disk', async () => {
    document.body.innerHTML = FORM;
    vi.spyOn(api, 'get').mockResolvedValue([{ name: 'haos.qcow2', path: '/i/haos.qcow2' }]);
    await bindDiskImages(document.body);
    const sel = document.getElementById('vm-create-disk-image');
    sel.value = '';
    sel.dispatchEvent(new Event('change'));
    expect(document.querySelector('input[value="iso"]').checked).toBe(true);
    sel.value = '/i/haos.qcow2';
    sel.dispatchEvent(new Event('change'));
    expect(document.querySelector('input[value="disk"]').checked).toBe(true);
    expect(await bindDiskImages(document.createElement('div'))).toEqual([]);
  });

  it('the installer list also reads the ready-made disks', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => (url.includes('disk-images') ? [{ name: 'haos.qcow2' }] : [{ name: 'a.iso' }]));
    await loadIsos();
    expect(vmState.isos.map((i) => i.name)).toEqual(['a.iso']);
    expect(vmState.diskImages.map((i) => i.name)).toEqual(['haos.qcow2']);
  });
});
