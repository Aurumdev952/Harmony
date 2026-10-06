import { readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { transformAsync } from '@babel/core';
import { defineConfig } from 'vitest/config';
import type { Plugin } from 'vitest/config';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const CLIENT = path.join(ROOT, 'web/client');
const TESTS = path.join(ROOT, 'tests/frontend');

// webpack resolves bare imports against web/client before node_modules
// (`resolve.modules` in web/webpack.config.js), so `util/ZenError` is a
// client module, not Node's `util`. Only imports made from client or test
// code take this route; dependencies keep normal Node resolution.
const CLIENT_ROOTS = new Set(
  readdirSync(CLIENT).map(name => name.replace(/\.jsx?$/, '')),
);

function clientRootImports(): Plugin {
  return {
    enforce: 'pre',
    name: 'harmony-client-root-imports',
    resolveId(source, importer) {
      if (!importer || !(importer.startsWith(CLIENT) || importer.startsWith(TESTS))) {
        return null;
      }
      if (!CLIENT_ROOTS.has(source.split('/')[0])) {
        return null;
      }
      return this.resolve(path.join(CLIENT, source), importer, { skipSelf: true });
    },
  };
}

// The client is Flow with legacy decorators, which esbuild cannot parse. Run
// the same Babel plugins and presets as web/webpack.config.js, minus the
// browser targeting that Node does not need. WP-6d/6e drop this once the
// code is TypeScript.
function flowBabel(): Plugin {
  return {
    enforce: 'pre',
    name: 'harmony-flow-babel',
    async transform(code, id) {
      if (!id.startsWith(CLIENT) || !/\.jsx?$/.test(id)) {
        return null;
      }
      const result = await transformAsync(code, {
        babelrc: false,
        configFile: false,
        filename: id,
        plugins: [
          ['@babel/plugin-proposal-decorators', { legacy: true }],
          ['@babel/plugin-proposal-class-properties', { loose: true }],
        ],
        presets: ['@babel/preset-flow', ['@babel/preset-react', { development: true }]],
        sourceMaps: true,
      });
      return result && result.code !== null && result.code !== undefined
        ? { code: result.code, map: result.map }
        : null;
    },
  };
}

export default defineConfig({
  plugins: [clientRootImports(), flowBabel()],
  test: {
    environment: 'jsdom',
    // Results must not depend on the machine's zone. APIToken dates shift a
    // day west of UTC (reported in WP-2e), so the suite pins one zone.
    env: { TZ: 'UTC' },
    include: ['tests/frontend/unit/**/*.test.js'],
    restoreMocks: true,
    setupFiles: ['tests/frontend/unit/setup.js', 'tests/frontend/unit/setupTranslations.js'],
  },
});
