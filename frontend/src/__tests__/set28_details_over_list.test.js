import { describe, it, expect } from 'vitest';
import fs from 'fs';
import path from 'path';

describe('the details panel lies over the list (SET-28 Files 2, finding 13)', () => {
  it('is positioned over the list, not beside it', () => {
    const css = fs.readFileSync(path.resolve(__dirname, '../styles/49-file-explorer-layout.css'), 'utf8');
    const rule = css.slice(css.indexOf('.fm-3pane-layout > .fm-inspector-pane {'));
    expect(rule).toMatch(/position: absolute/);
    expect(rule.slice(0, rule.indexOf('}'))).toMatch(/right: 0/);
    expect(css).toMatch(/\.fm-3pane-layout \{ position: relative; \}/);
  });
});
