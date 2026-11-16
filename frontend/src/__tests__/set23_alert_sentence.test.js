import { describe, it, expect, vi } from 'vitest';
import { api } from '../api.js';
import { alertDestinations, alertSentence, fetchAndRenderNotificationConfig } from '../components/management/notifications.js';

describe('Send alerts says where alerts go (SET-23, Settings 4)', () => {
  it('names only the channels that are on and set up', () => {
    expect(alertDestinations({ email_enabled: true, smtp_host: 'mail', telegram_enabled: true, discord_enabled: true, discord_webhook_url: 'x' })).toEqual(['e-mail', 'Discord']);
    expect(alertDestinations({ apprise_urls: ['a'], ntfy_enabled: true, ntfy_topic: 't', webhook_enabled: true, webhook_url: 'u' })).toEqual(['ntfy', 'a webhook', 'Apprise']);
  });

  it('is amber when nobody would be told', () => {
    expect(alertSentence({ enabled: false })).toEqual(['Alerts are off: nobody is told when something breaks.', true]);
    expect(alertSentence({ enabled: true })[1]).toBe(true);
    expect(alertSentence({ enabled: true, email_enabled: true, smtp_host: 'm', ntfy_enabled: true, ntfy_topic: 't' })).toEqual(['Alerts go to e-mail and ntfy.', false]);
  });

  it('the card shows the sentence from the saved settings', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ enabled: true });
    document.body.innerHTML = '<input type="checkbox" id="notif-master-enabled"><p id="notif-master-sentence"></p>';
    await fetchAndRenderNotificationConfig();
    const p = /** @type {HTMLElement} */ (document.getElementById('notif-master-sentence'));
    expect(p.textContent).toContain('Nobody is told');
    expect(p.classList.contains('is-warn')).toBe(true);
    vi.restoreAllMocks();
  });
});
