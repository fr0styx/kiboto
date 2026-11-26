import { describe, it, expect, beforeEach } from 'vitest';
import { clearSelectedContainers, getSelectedContainerIds } from '../components/docker-table.js';

beforeEach(() => {
  localStorage.clear();
  clearSelectedContainers();
});

/** @param {Element|null} el */
const box = (el) => /** @type {HTMLInputElement} */ (el);
/** @param {HTMLInputElement} el @param {boolean} on */
const tick = (el, on) => {
  el.checked = on;
  el.dispatchEvent(new Event('change', { bubbles: true }));
};

describe('a stack header ticks every container of that stack (Apps, Docker details)', () => {
  it('ticks and clears the stack, follows single rows, and leaves other stacks alone', async () => {
    const { renderContainersWindowTable } = await import('../components/containers-manager.js');
    document.body.innerHTML = `<div id="containers-manager-window">
      <div id="cw-docker-bulk-bar" style="display:none"><span id="cw-docker-bulk-count">0</span></div>
      <table><tbody id="cw-docker-containers-tbody"></tbody></table></div>`;
    localStorage.setItem('kiboto_apps_details', '1');
    renderContainersWindowTable([
      { id: 'w', name: 'web', stack: 'immich', state: 'running', status: 'Up', ports: [] },
      { id: 'd', name: 'db', stack: 'immich', state: 'running', status: 'Up', ports: [] },
      { id: 'r', name: 'radarr', stack: 'arr', state: 'running', status: 'Up', ports: [] },
      { id: 'j', name: 'jellyfin', state: 'running', status: 'Up', ports: [] },
    ]);
    const tbody = /** @type {HTMLElement} */ (document.getElementById('cw-docker-containers-tbody'));
    const head = box(tbody.querySelector('.cw-stack-select[data-stack="immich"]'));
    expect(head.getAttribute('aria-label')).toBe('Select everything in immich');
    expect(head.checked).toBe(false);

    tick(head, true);
    expect(getSelectedContainerIds().sort()).toEqual(['d', 'w']);
    expect(box(tbody.querySelector('.docker-row-select[data-id="w"]')).checked).toBe(true);
    expect(
      tbody.querySelector('.docker-row-select[data-id="d"]')?.closest('tr')?.classList.contains('docker-row-selected')
    ).toBe(true);
    expect(box(tbody.querySelector('.docker-row-select[data-id="r"]')).checked).toBe(false);
    expect(document.getElementById('cw-docker-bulk-bar')?.style.display).toBe('flex');
    expect(document.getElementById('cw-docker-bulk-count')?.textContent).toBe('2');

    // one row cleared: the stack shows a dash
    tick(box(tbody.querySelector('.docker-row-select[data-id="w"]')), false);
    expect(head.checked).toBe(false);
    expect(head.indeterminate).toBe(true);

    // the apps in no stack have a box too
    tick(box(tbody.querySelector('.cw-stack-select[data-stack=""]')), true);
    expect(getSelectedContainerIds().sort()).toEqual(['d', 'j']);

    tick(head, false);
    expect(getSelectedContainerIds()).toEqual(['j']);
    expect(head.indeterminate).toBe(false);
  });
});
