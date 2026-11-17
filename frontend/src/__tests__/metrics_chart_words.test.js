// Activity finding 25: the chart has a text alternative for screen readers.
import { describe, it, expect } from 'vitest';
import { chartSummary } from '../components/metrics-chart.js';

describe('the chart in words', () => {
  it('says each line from lowest to highest and its average', () => {
    const s = chartSummary([
      { label: 'Processor (%)', data: [10, 30, 20] },
      { label: 'CPU (°C)', data: [40.04, 50, null, 45] },
      { label: 'Empty', data: [] },
    ], 'Last 24 Hours');
    expect(s).toBe('Chart, Last 24 Hours. Processor (%): from 10 to 30, on average 20; CPU (°C): from 40 to 50, on average 45.');
    expect(chartSummary([], 'Last 7 Days')).toBe('Chart, Last 7 Days: no readings.');
  });
});
