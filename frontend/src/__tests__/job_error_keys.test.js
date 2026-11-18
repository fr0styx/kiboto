// A job's error in the reader's language when the server sends its key (app updates, 17 Nov).
import { describe, it, expect, afterEach } from 'vitest';
import { jobDetail } from '../components/jobs-centre.js';
import { setLanguage } from '../i18n.js';

describe('job errors in words', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('the key wins, then the error, then the detail line', async () => {
    await setLanguage('de');
    expect(
      jobDetail({
        error: 'web could not be updated: x.',
        error_id: 'jobs.e.app_update_failed',
        error_params: { name: 'web', reason: 'x' },
      })
    ).toBe('web konnte nicht aktualisiert werden: x.');
    expect(jobDetail({ error_id: 'jobs.e.unknown_key', error: 'Disk full' })).toBe('Disk full'); // a newer server's key: its English
    expect(jobDetail({ error: 'Disk full' })).toBe('Disk full');
    expect(
      jobDetail({ detail: 'Updating web', detail_id: 'jobs.d.app_updating', detail_params: { name: 'web' } })
    ).toBe('web wird aktualisiert');
    expect(jobDetail({ detail_id: 'jobs.d.app_going_back' })).toBe('Zurück zu den alten Versionen');
    expect(jobDetail({ detail: 'as sent' })).toBe('as sent');
    expect(jobDetail({})).toBe('');
  });
});
