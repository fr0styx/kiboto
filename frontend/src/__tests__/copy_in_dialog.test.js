/** #71: on plain http the copy goes through a hidden box; with a dialog open it must be inside it. */
import { describe, it, expect, vi, afterEach } from 'vitest';

const { copyText } = await import('../utils.js');

describe('copying on plain http', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  it('puts the hidden box inside the open dialog, where it can be selected', async () => {
    document.body.innerHTML = `<dialog id="d" open><button id="b">Copy</button></dialog>`;
    document.getElementById('b').focus();
    let parent = null;
    document.execCommand = vi.fn(() => {
      parent = document.activeElement?.parentElement?.id;
      return true;
    });
    await copyText('\\\\nas\\photos');
    expect(parent).toBe('d');
  });

  it('says it failed when the box could not take the focus', async () => {
    document.execCommand = vi.fn(() => true);
    vi.spyOn(HTMLTextAreaElement.prototype, 'focus').mockImplementation(() => {});
    await expect(copyText('smb://nas/photos')).rejects.toThrow('Copy failed');
  });
});
