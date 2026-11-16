import { describe, it, expect } from 'vitest';
import { firstOpenSize, FileManagerWindow } from '../components/file-manager.js';

describe('the File Explorer opens at a usable size (SET-28 Files 2, finding 14)', () => {
  it('roomy on a big screen, inside a small one, never below the smallest size', () => {
    expect(firstOpenSize(1920, 1080)).toEqual({ width: 1000, height: 640 });
    expect(firstOpenSize(1024, 700)).toEqual({ width: 976, height: 560 });
    expect(firstOpenSize(500, 400)).toEqual({ width: 480, height: 320 });
  });

  it('a window with no saved place gets that size and is centred below the top bar', () => {
    const el = document.createElement('div');
    FileManagerWindow.prototype.placeIfUnplaced.call({ windowEl: el });
    expect(el.style.width).toBe(`${firstOpenSize(window.innerWidth, window.innerHeight).width}px`);
    expect(el.style.height).toBe(`${firstOpenSize(window.innerWidth, window.innerHeight).height}px`);
    expect(parseInt(el.style.top, 10)).toBeGreaterThanOrEqual(56);
  });

  it('a saved size is kept', () => {
    const el = document.createElement('div');
    el.style.width = '700px';
    el.style.height = '450px';
    FileManagerWindow.prototype.placeIfUnplaced.call({ windowEl: el });
    expect(el.style.width).toBe('700px');
    expect(el.style.height).toBe('450px');
  });
});
