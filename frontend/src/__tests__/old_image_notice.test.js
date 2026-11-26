// Kiboto 2.2 stops publishing the image's old name: About says so where a container still uses it.
import { describe, it, expect } from 'vitest';

const { oldImageNotice, showOldImageNotice } = await import('../components/management/system.js');

describe('the old image name', () => {
  it('is named, with what to change, only where it is used', () => {
    expect(oldImageNotice({ old_image_name: 'ghcr.io/x/old' })).toContain(
      'change ghcr.io/x/old to ghcr.io/fr0styx/kiboto'
    );
    expect(oldImageNotice({ old_image_name: '' })).toBe('');
    expect(oldImageNotice(null)).toBe('');
  });

  it('shows its line in About, and hides it again', () => {
    document.body.innerHTML = '<div id="about-old-image-box" hidden><div id="about-old-image"></div></div>';
    showOldImageNotice({ old_image_name: 'ghcr.io/x/old' });
    expect(document.getElementById('about-old-image-box').hidden).toBe(false);
    expect(document.getElementById('about-old-image').textContent).toContain('Kiboto 2.2');
    showOldImageNotice({});
    expect(document.getElementById('about-old-image-box').hidden).toBe(true);
    document.body.innerHTML = '';
    expect(showOldImageNotice({ old_image_name: 'ghcr.io/x/old' })).toContain('Kiboto 2.2');
  });
});
