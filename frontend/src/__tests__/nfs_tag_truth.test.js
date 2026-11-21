/** A share that is set to NFS on an install with no NFS server shows as not running, not as shared. */
import { describe, it, expect } from 'vitest';
import { shareProtocolTags } from '../components/chassis-visualizer.js';

describe('the NFS tag follows the server', () => {
  const share = { name: 'films', export_smb: false, export_nfs: true };
  it('says not running where this install has no NFS server', () => {
    document.body.innerHTML = shareProtocolTags(share, { nfs: { running: false } });
    const tag = [...document.querySelectorAll('.proto-tag')].find((x) => x.textContent === 'NFS');
    expect(tag.className).toContain('proto-down');
    expect(tag.title).toContain('not running');
  });
  it('says shared where a server runs, and where the host serves NFS itself', () => {
    for (const services of [{ nfs: { running: true } }, { nfs: null }, {}]) {
      document.body.innerHTML = shareProtocolTags(share, services);
      const tag = [...document.querySelectorAll('.proto-tag')].find((x) => x.textContent === 'NFS');
      expect(tag.className).toContain('proto-on');
    }
  });
});
