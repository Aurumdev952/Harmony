# Vite 8 in Harmony

Sources: https://vite.dev/llms.txt and https://vite.dev/guide/migration. Vite 8 uses Rolldown for bundling, Oxc for transforms and Lightning CSS for minifying. It needs Node 20.19 or 22.12 or later. Harmony standardises on Node 24 LTS (FE-11).

## Config facts

- **Rolldown options.** Use `build.rolldownOptions`. `rollupOptions` is auto-converted but deprecated.
- **Oxc, not esbuild.** `esbuild` and `optimizeDeps.esbuildOptions` are deprecated in favour of `oxc` and `rolldownOptions`.
- **Chunking.** `manualChunks` in object form is gone and the function form is deprecated. Use Rolldown `codeSplitting` groups if vendor splitting is needed. Measure before splitting.
- **CJS interop.** The `default` import from old CommonJS packages changed. Expect breakage in old dependencies and fix it at the import site.
- **JSX in `.js` files.** About half the JSX lives in `.js` files. Configure the transform to treat `web/client/**/*.js` as JSX until TypeScript conversion renames them.

## Babel pass (until Flow, decorators and Relay are gone)

- Oxc cannot strip Flow or lower legacy decorators.
- `@vitejs/plugin-react` 6 removed its `babel` option.
- Run Babel through `@rolldown/plugin-babel`, restricted to `web/client/**`, with:
  - `babel-plugin-syntax-hermes-parser`, or `@babel/plugin-transform-flow-strip-types`;
  - `@babel/plugin-proposal-decorators` with `{ version: "legacy" }`, plus class properties;
  - `babel-plugin-relay`, until WP-5e removes Relay.
- Remove each plugin in the WP that removes its reason. When none remain, delete the Babel pass.

## Multi-page backend integration (WP-6b)

- **Entries.** One entry per file in `web/client/entryPoints/`, plus the SCSS entry `web/public/scss/entry.scss` until WP-7h. Put them in `build.rolldownOptions.input` and set `build.manifest: true`.
- **Manifest (contract C-7).** `.vite/manifest.json` maps each entry to `{file, css[], imports[], dynamicImports[]}`. The template helper replaces `bundle_resource_url` (`web/server/templates/bundle_resource.template`, `web/server/util/template_renderer.py:35-43`). For each entry it emits:
  - `<script type="module">` for the entry,
  - `<link rel="modulepreload">` for its `imports`, walked recursively,
  - `<link rel="stylesheet">` for its `css`.
- **Development.** The template injects `@vite/client`, the React refresh preamble and the entry module from the Vite dev server.
- **Delete the webpack proxy** (`web/server/routes/webpack_dev_proxy.py`) and the `vendor` and `commons` script tags in `layout.html`.
- **Aliases.** Keep bare imports (`components/...`, `models/...`, `services/...`, `util/...`, `lib/...`, `vendor/...`, `decorators/...`, `translate`) working with `resolve.alias`, one per top-level folder in `web/client`. Generate the list from the folders. Do not hand-maintain it.
- **Globals.** `__DEV__` and `process.env.NODE_ENV` come from `define`. Moment locales are dropped until moment is removed.
- **Static assets.** Fonts and images under `web/public` are served from `publicDir` or imported. The runtime vendor registry (`web/client/vendor/registry/index.js`) keeps loading `web/public/js/vendor/*.js` until WP-6f.

## Measure

Record per-entry JS and CSS size (gzip) before and after in the WP file. The webpack baseline is in the WP-1g evidence.
