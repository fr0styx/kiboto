// Security: "Checks that use the internet" (owner, 19 Nov 2026).
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../api.js';
import { showToast } from '../toast.js';
import { outsideChecksNodes, renderOutsideChecks, WORDS } from '../components/management/outside-checks.js';

vi.mock('../toast.js', async (orig) => ({ ...(await orig()), showToast: vi.fn() }));

describe('checks that use the internet', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.mocked(showToast).mockClear();
    document.body.innerHTML = '';
  });

  it('shows a switch and what is sent for each check it knows, and skips the rest', () => {
    const nodes = outsideChecksNodes([
      { name: 'leaked_passwords', enabled: true },
      { name: 'from_a_newer_server', enabled: true },
    ]);
    expect(nodes.length).toBe(1);
    expect(nodes[0].querySelector('input').checked).toBe(true);
    expect(nodes[0].textContent).toContain('Refuse passwords found in known data leaks');
    expect(nodes[0].textContent).toContain('never the password');
    expect(outsideChecksNodes(null)).toEqual([]);
    expect(Object.keys(WORDS)).toContain('leaked_passwords');
    const all = outsideChecksNodes([
      { name: 'leaked_passwords', enabled: false },
      { name: 'internet_speed', enabled: false },
      { name: 'weakness_feed', enabled: true },
    ]);
    expect(all.length).toBe(3);
    expect(all[2].textContent).toContain('Warn about apps with a weakness that is being attacked');
    expect(all[2].textContent).toContain('Nothing about your NAS is sent');
  });

  it('sits under the two-step rule, saves a change and says so', async () => {
    document.body.innerHTML = '<div id="sec-advisor-card"></div><div id="sec-mfa-policy"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({ checks: [{ name: 'leaked_passwords', enabled: false }] });
    const put = vi.spyOn(api, 'put').mockResolvedValue({});
    expect(await renderOutsideChecks()).toBe(true);
    await renderOutsideChecks(); // drawn again: still one box, bound once
    const box = document.getElementById('sec-outside-checks');
    expect(document.querySelectorAll('#sec-outside-checks').length).toBe(1);
    expect(box.previousElementSibling.id).toBe('sec-mfa-policy');
    expect(box.querySelector('h4').textContent).toBe('Checks that use the internet');
    const input = box.querySelector('input');
    input.checked = true;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await vi.waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put).toHaveBeenCalledWith('/api/security/outside-checks', { name: 'leaked_passwords', enabled: true });
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Turned on.', 'success'));
    input.checked = false;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith('Turned off. Nothing more is asked.', 'success'));
    box.dispatchEvent(new Event('change', { bubbles: true })); // not a switch: nothing
    expect(put).toHaveBeenCalledTimes(2);
  });

  it('puts the switch back when the change is refused', async () => {
    document.body.innerHTML = '<div id="sec-advisor-card"></div>';
    vi.spyOn(api, 'get').mockResolvedValue({ checks: [{ name: 'leaked_passwords', enabled: false }] });
    vi.spyOn(api, 'put').mockRejectedValue(new Error('no right'));
    await renderOutsideChecks();
    const input = document.querySelector('#sec-outside-checks input');
    input.checked = true;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await vi.waitFor(() => expect(showToast).toHaveBeenCalledWith("Couldn't change it: no right", 'error'));
    expect(input.checked).toBe(false);
  });

  it('hides for someone who may not see it, and needs the Security page', async () => {
    expect(await renderOutsideChecks()).toBe(false);
    document.body.innerHTML = '<div id="sec-advisor-card"></div>';
    vi.spyOn(api, 'get').mockRejectedValue(new Error('403'));
    expect(await renderOutsideChecks()).toBe(false);
    expect(document.getElementById('sec-outside-checks').hidden).toBe(true);
  });
});
