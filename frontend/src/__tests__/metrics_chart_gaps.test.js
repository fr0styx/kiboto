// Activity finding 11: hours when the NAS was off break the line instead of joining it up.
import { describe, it, expect } from 'vitest';
import { withGaps } from '../components/metrics-chart.js';

describe('gaps where the NAS was off', () => {
  it('puts one gap point where readings jump', () => {
    const pts = [0, 300, 600, 900, 900 + 3 * 3600, 900 + 3 * 3600 + 300].map((ts) => ({ ts, cpu_util: 5 }));
    const out = withGaps(pts);
    expect(out).toHaveLength(7);
    expect(out[4]).toEqual({ ts: 1200, gap: true });
    expect(out.filter((d) => d.gap)).toHaveLength(1);
  });

  it('leaves short or steady lists alone', () => {
    expect(withGaps(null)).toEqual([]);
    const two = [{ ts: 0 }, { ts: 9999 }];
    expect(withGaps(two)).toBe(two);
    const steady = [0, 300, 600, 900].map((ts) => ({ ts }));
    expect(withGaps(steady)).toHaveLength(4);
  });
});
