// Secure Boot on Kiboto OS: About says when one step is left at the machine's screen.
import { describe, it, expect } from 'vitest';

const { secureBootNotice, showSecureBootNotice } = await import('../components/management/system.js');

describe('Secure Boot in About', () => {
  it('says what is left only while the key waits for the step at the screen', () => {
    expect(secureBootNotice({ secure_boot: 'waiting' })).toContain('Enroll MOK');
    expect(secureBootNotice({ secure_boot: 'waiting' })).not.toMatch(/\d{8}/); // the code stays on the machine's screen
    expect(secureBootNotice({ secure_boot: 'on' })).toBe('');
    expect(secureBootNotice({ secure_boot: '' })).toBe('');
    expect(secureBootNotice(null)).toBe('');
  });

  it('shows its line in About, and hides it again', () => {
    document.body.innerHTML = '<div id="about-secure-boot-box" hidden><div id="about-secure-boot"></div></div>';
    showSecureBootNotice({ secure_boot: 'waiting' });
    expect(document.getElementById('about-secure-boot-box').hidden).toBe(false);
    expect(document.getElementById('about-secure-boot').textContent).toContain('Perform MOK management');
    showSecureBootNotice({ secure_boot: 'on' });
    expect(document.getElementById('about-secure-boot-box').hidden).toBe(true);
    document.body.innerHTML = '';
    expect(showSecureBootNotice({ secure_boot: 'waiting' })).toContain('Storage pools are ready');
  });
});
