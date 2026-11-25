import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('../toast.js', () => ({ showToast: vi.fn() }));
const { api } = await import('../api.js');
const card = await import('../components/management/family-portal.js');
const portal = await import('../../public/portal/portal.js');

const VIEW = {
  on: false,
  live: false,
  tailscale: true,
  address: 'https://attic.example.ts.net:8443/portal/',
  funnel: { ready: false, funnel: false, https: true, approve_url: 'https://login.tailscale.com/f/funnel?node=n1' },
  people: [
    { id: 'u1', name: 'Gran <b>', allowed: true, passkey: false, invite_until: 0, signed_in: false },
    { id: 'u2', name: 'Kid', allowed: false, passkey: false, invite_until: 0, signed_in: false },
  ],
};

describe('family portal card (ADR 0007)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="away-cards-grid"></div>';
  });

  it('says it is off, shows the Tailscale step and each person, names escaped', () => {
    const html = card.familyPortalHtml(VIEW);
    expect(html).toContain('Off. Nothing of it is on the internet.');
    expect(html).toContain('Allow Funnel for this NAS');
    expect(html).toContain('Gran &lt;b&gt;');
    expect(html).toContain('data-fp-join="u1"');
    expect(html).not.toContain('data-fp-join="u2"');
    expect(card.familyPortalHtml({ ...VIEW, on: true, live: true })).toContain(
      'On at https://attic.example.ts.net:8443/portal/'
    );
    expect(card.familyPortalHtml({ ...VIEW, on: true, live: false })).toContain('publishing it right now');
    expect(card.familyPortalHtml({ tailscale: false })).toContain('Connect Tailscale first');
  });

  it('turns it on, allows a person, makes a join link and copies the message', async () => {
    api.get.mockResolvedValue(VIEW);
    api.put.mockResolvedValue({ ...VIEW, on: true, live: true });
    await card.loadFamilyPortalCard();
    const click = (sel) => card.onPortalClick({ target: document.querySelector(sel) });
    await click('[data-fp="toggle"]');
    expect(api.put).toHaveBeenCalledWith('/api/network/family-portal', { on: true });
    await click('[data-fp-allow="u2"]');
    expect(api.put).toHaveBeenCalledWith('/api/network/family-portal/people/u2', { allowed: true });
    api.post.mockResolvedValue({ link: 'https://attic.example.ts.net:8443/portal/#join=abc' });
    api.get.mockResolvedValue({ ...VIEW, people: [{ ...VIEW.people[0], invite_until: 1900000000 }] });
    await click('[data-fp-join="u1"]');
    expect(api.post).toHaveBeenCalledWith('/api/network/family-portal/people/u1/invite', {});
    expect(document.querySelector('[data-fp-withdraw="u1"]')).not.toBeNull();
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    await click('[data-fp-copy="u1"]');
    expect(writeText.mock.calls[0][0]).toContain('#join=abc');
    api.delete.mockResolvedValue(VIEW);
    await click('[data-fp-withdraw="u1"]');
    expect(api.delete).toHaveBeenCalledWith('/api/network/family-portal/people/u1/invite');
  });
});

describe('family portal card: the rarer turns', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '<div id="away-cards-grid"></div>';
  });

  it('asks for HTTPS certificates too, and names each state a person can be in', () => {
    const html = card.familyPortalHtml({
      ...VIEW,
      funnel: { ready: false, funnel: true, https: false, dns_url: 'https://login.tailscale.com/admin/dns' },
      people: [
        { id: 'a', name: 'A', allowed: true, passkey: true, signed_in: true },
        { id: 'b', name: 'B', allowed: true, passkey: true, signed_in: false },
      ],
    });
    expect(html).toContain('Turn on HTTPS certificates');
    expect(html).not.toContain('Allow Funnel for this NAS');
    expect(html).toContain('Signed in now');
    expect(html).toContain('Has a passkey');
  });

  it('says what went wrong, and shows the link when copying does not work', async () => {
    const { showToast } = await import('../toast.js');
    api.get.mockResolvedValue(VIEW);
    await card.loadFamilyPortalCard();
    api.put.mockRejectedValue(new Error('Tailscale is busy'));
    await card.onPortalClick({ target: document.querySelector('[data-fp="toggle"]') });
    expect(showToast).toHaveBeenCalledWith('Tailscale is busy', 'error');
    api.post.mockResolvedValue({ link: 'https://x/portal/#join=zzz' });
    api.get.mockResolvedValue(VIEW);
    await card.onPortalClick({ target: document.querySelector('[data-fp-join="u1"]') });
    Object.assign(navigator, { clipboard: { writeText: vi.fn(() => Promise.reject(new Error('no'))) } });
    await card.onPortalClick({ target: document.querySelector('[data-fp-copy="u1"]') });
    expect(showToast).toHaveBeenCalledWith('https://x/portal/#join=zzz', 'info');
    api.get.mockRejectedValue(new Error('offline'));
    await card.loadFamilyPortalCard();
    expect(document.getElementById('fp-body').textContent).toBe('offline');
  });
});

describe('the portal page (ADR 0007)', () => {
  it('speaks the browser language and fills in names', () => {
    expect(portal.pickLang(['de-AT', 'en'])).toBe('de');
    expect(portal.pickLang(['pt-BR'])).toBe('en');
    portal.setLang('fr');
    expect(portal.tr('signin')).toBe('Se connecter avec une clé d’accès');
    expect(portal.tr('failed', { why: 'x' })).toBe('Ça n’a pas marché : x');
    portal.setLang('xx');
    expect(portal.tr('up')).toBe('Back');
  });

  it('knows folders, pictures, videos and files, and reads the join token after #', () => {
    expect(portal.kindOf({ name: 'a', is_dir: true })).toBe('folder');
    expect(portal.kindOf({ name: 'IMG_1.HEIC' })).toBe('picture');
    expect(portal.kindOf({ name: 'clip.mov', ext: '.mov' })).toBe('video');
    expect(portal.kindOf({ name: 'notes.pdf' })).toBe('file');
    expect(portal.joinToken('#join=abcdefghijklmnopqrstuvwxyz012345')).toBe('abcdefghijklmnopqrstuvwxyz012345');
    expect(portal.joinToken('#join=short')).toBe('');
    expect(portal.joinToken('')).toBe('');
  });

  it('builds entries without letting a name become markup', () => {
    const nodes = portal.entryNodes(document, [
      { name: '..', path: '/p', is_dir: true },
      { name: '<img src=x onerror=alert(1)>.jpg', path: '/p/a.jpg', mtime: 5 },
      { name: 'Trip', path: '/p/Trip', is_dir: true },
      { name: 'a b.pdf', path: '/p/a b.pdf' },
    ]);
    expect(nodes).toHaveLength(3);
    expect(nodes[0].querySelector('.name').textContent).toBe('<img src=x onerror=alert(1)>.jpg');
    expect(nodes[0].querySelectorAll('img')).toHaveLength(1);
    expect(nodes[0].querySelector('img').getAttribute('src')).toBe('/portal/api/picture?thumb=1&path=%2Fp%2Fa.jpg&v=5');
    expect(nodes[1].querySelector('button').dataset.kind).toBe('folder');
    expect(nodes[2].querySelector('a').getAttribute('href')).toBe('/portal/api/file?path=%2Fp%2Fa%20b.pdf');
  });

  it('turns passkey options and answers between base64url and bytes', () => {
    const b = portal.toB64(new Uint8Array([251, 255, 0, 1]).buffer);
    expect(b).toBe('-_8AAQ');
    expect(Array.from(new Uint8Array(portal.fromB64(b)))).toEqual([251, 255, 0, 1]);
    const c = portal.creationOptions({
      challenge: 'AQI',
      user: { id: 'AwQ', name: 'g' },
      excludeCredentials: [{ id: 'BQ' }],
    });
    expect(new Uint8Array(c.challenge)[1]).toBe(2);
    expect(new Uint8Array(c.excludeCredentials[0].id)[0]).toBe(5);
    const r = portal.requestOptions({ challenge: 'AQI', allowCredentials: [{ id: 'BQ' }] });
    expect(new Uint8Array(r.allowCredentials[0].id)[0]).toBe(5);
    const cred = {
      id: 'x',
      rawId: new Uint8Array([1]).buffer,
      type: 'public-key',
      response: { clientDataJSON: new Uint8Array([2]).buffer, signature: new Uint8Array([3]).buffer },
    };
    expect(portal.credentialJSON(cred)).toEqual({
      id: 'x',
      rawId: 'AQ',
      type: 'public-key',
      response: { clientDataJSON: 'Ag', signature: 'Aw' },
      clientExtensionResults: {},
    });
    expect(portal.credentialJSON({ toJSON: () => ({ id: 'own' }) })).toEqual({ id: 'own' });
  });
});
