import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    pool: 'vmThreads',
    setupFiles: ['./frontend/src/__tests__/setup.js'],
    // A limit against hangs, not a speed check. Tests that parse the whole Settings markup or draw
    // the full time-zone list ran past vitest's 5 s default on a busy machine (gate beside other
    // jobs, CI under load) and failed at random while they pass alone in under a second.
    testTimeout: 20000,
    hookTimeout: 20000,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html', 'lcov'],
      include: ['frontend/src/**/*.js'],
      // locale data is loaded by tests but isn't code: counting it inflated the numbers (NARC-4)
      exclude: ['frontend/src/__tests__/**', 'frontend/src/locales/**'],
      // OPS-16, ARC-26: floors a little under today's numbers without locale data (lines / statements /
      // functions / branches 74.1 / 71.5 / 64.2 / 60.2 on 3 Nov 2026); raise them as coverage grows
      thresholds: { lines: 73, statements: 70, functions: 63, branches: 59 },
    },
  },
});
