// Five-language sweep: names the server makes up on its own are shown in the reader's language.
import { describe, it, expect, afterEach } from 'vitest';
import { poolName, shareComment, accessWords } from '../components/pool-names.js';
import { fileKind } from '../components/file-kind.js';
import { setLanguage } from '../i18n.js';

describe('server-made names', () => {
  afterEach(async () => { await setLanguage('en'); });

  it('the generic main pool and its share are translated, chosen names are not', async () => {
    expect(poolName('Primary Storage Pool')).toBe('Main storage pool');
    await setLanguage('de');
    expect(poolName('Primary Storage Pool')).toBe('Hauptspeicher-Pool');
    expect(shareComment('Kiboto Primary Storage Pool')).toBe('Der Hauptspeicher-Pool');
    expect(poolName('Fotos')).toBe('Fotos');
    expect(shareComment('Unsere Urlaubsbilder')).toBe('Unsere Urlaubsbilder');
    expect(poolName(undefined)).toBe('');
    expect(shareComment(null)).toBe('');
  });

  it('access and file kinds in German', async () => {
    await setLanguage('de');
    expect(accessWords(true)).toBe('Nur lesen');
    expect(accessWords(false)).toBe('Lesen und schreiben');
    expect(fileKind({ name: 'Fotos', is_dir: true })).toBe('Ordner');
    expect(fileKind({ name: 'gdrive', is_dir: true }, true)).toBe('Cloud-Laufwerk');
    expect(fileKind({ name: 'sdb', is_dir: true }, false, true)).toBe('Laufwerk');
    expect(fileKind({ name: 'brief.pdf' })).toBe('PDF');
    expect(fileKind({ name: 'README' })).toBe('Datei');
  });
});
