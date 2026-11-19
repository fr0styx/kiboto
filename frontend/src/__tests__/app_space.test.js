// Re-audit R4: space each app uses, in the Docker cleanup window.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { appSpaceLine, appSpaceNodes, loadAppSpace } from '../components/management/app-space.js';

const IMMICH = {
  name: 'immich',
  data_bytes: 2_005_000_000,
  program_bytes: 300_000_000,
  folders: [{ path: '/mnt/user/appdata/immich', bytes: null, state: 'not_measured' }],
  shared_folders: 1,
};

describe('space each app uses', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('says the data first, then the program, then what is not counted', () => {
    const line = appSpaceLine(IMMICH);
    expect(line).toMatch(/^1\.9 GB of data · program 286(\.\d)? MB/);
    expect(line).toContain('its folders are not measured yet');
    expect(line).toContain('shared folders are not counted');
    const measured = appSpaceLine({
      name: 'x',
      data_bytes: 10,
      folders: [{ state: 'asleep' }, { state: 'partial' }, { state: 'measured' }],
    });
    expect(measured).toContain('sleeping drive');
    expect(measured).toContain('counted in part');
    expect(measured).not.toContain('not measured yet');
    expect(appSpaceLine({ name: 'bare' })).toMatch(/^0 B of data · program 0 B$/);
  });

  it('lists the apps, or says there are none', () => {
    const [list] = appSpaceNodes({ apps: [IMMICH, { name: 'pihole', data_bytes: 0, program_bytes: 9 }] });
    expect(list.querySelectorAll('li').length).toBe(2);
    expect(list.querySelector('strong').textContent).toBe('immich');
    expect(appSpaceNodes({ apps: [] })[0].textContent).toBe('No apps are installed.');
    expect(appSpaceNodes(null)[0].textContent).toBe('No apps are installed.');
  });

  it('loads at once, then measures the folders when asked', async () => {
    document.body.innerHTML = '<div id="dpm-app-space"></div>';
    const get = vi
      .spyOn(api, 'get')
      .mockResolvedValueOnce({ apps: [IMMICH], folders_measured: false })
      .mockResolvedValueOnce({
        apps: [{ ...IMMICH, folders: [{ state: 'measured', bytes: 1500 }] }],
        folders_measured: true,
      });
    await loadAppSpace();
    const box = document.getElementById('dpm-app-space');
    expect(get).toHaveBeenLastCalledWith('/api/docker/apps/space');
    const more = box.querySelector('button');
    expect(more.textContent).toBe('Measure the folders too');
    more.click();
    expect(box.textContent).toContain('Measuring the folders');
    await vi.waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/docker/apps/space?folders=true'));
    await vi.waitFor(() => expect(box.querySelector('button')).toBeNull());
    expect(box.textContent).not.toContain('not measured yet');
  });

  it('says so when Docker does not answer, shows no button for no apps, and needs its box', async () => {
    document.body.innerHTML = '<div id="dpm-app-space"></div>';
    vi.spyOn(api, 'get').mockRejectedValueOnce(new Error('daemon busy')).mockResolvedValueOnce({ apps: [] });
    expect(await loadAppSpace()).toBeNull();
    expect(document.getElementById('dpm-app-space').textContent).toContain('daemon busy');
    await loadAppSpace();
    expect(document.querySelector('#dpm-app-space button')).toBeNull();
    expect(await loadAppSpace(null)).toBeNull();
  });
});
