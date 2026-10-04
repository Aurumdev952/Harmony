# Phase 6. Frontend platform: fetch, Vite, React 19, TypeScript

Back to [overview](overview.md).

**Goal.** Put the frontend on a current toolchain without changing how it looks. Phase 7 needs React 19 and Tailwind v4 in place, and this phase delivers them. Each unit ships behind the existing visuals, and the Playwright smoke suite stays green.

## 6a. HTTP without jQuery or bluebird

- **Changes.**
  - Rewrite `web/client/services/APIService.js` and `web/client/util/ZenClient.js` on `fetch`, with an `AbortController` for cancellation.
  - Replace bluebird (136 files) with native promises by codemod. Cancellation moves from `promise.cancel()` to passing an `AbortSignal`.
  - Rewrite `fetchGeoJsonTiles.js` on `fetch`.
  - Remove jQuery from `layout.html`.
- **Verification.**
  - Unit tests for `APIService` cover errors, cancellation and JSON parsing.
  - Playwright smoke suite.
  - `grep` confirms no `$.` or `bluebird` imports.

## 6b. Vite 8

- **Changes.**
  - Add `vite.config.ts` with all 19 entries in `build.rolldownOptions.input` and `build.manifest: true`.
  - Add `resolve.alias` entries for each top-level folder under `web/client`. Treat `.js` files as JSX.
  - Run one Babel pass through `@rolldown/plugin-babel` with the Flow strip plugin, `babel-plugin-relay` (until phase 5e removes it) and legacy decorators.
  - SCSS still compiles to one `bundle.css` entry.
  - Rewrite the Jinja `bundle_resource_url` macro (`web/server/templates/bundle_resource.template`, `web/server/util/template_renderer.py:35-43`) as a manifest helper that emits module scripts, CSS links and `modulepreload` tags. In development it emits `@vite/client` and the React refresh preamble.
  - Delete the `/build/` webpack proxy (`web/server/routes/webpack_dev_proxy.py`).
  - Serve the vendor registry scripts (`web/client/vendor/registry/index.js`) from `public/` unchanged for now.
  - Delete the webpack configs and loaders.
- **Data structure.** `ViteManifestEntry = {file, css[], imports[], dynamicImports[]}`.
- **Verification.**
  - `pnpm build` produces hashed assets and a manifest.
  - Every page renders in development with HMR and in production (`verify` skill).
  - Bundle sizes per entry are recorded against the webpack baseline.

## 6c. React 19

- **Changes.**
  - Replace the 23 `ReactDOM.render` calls with `createRoot`.
  - Replace the decorators by codemod: `@autobind` (624 uses) becomes arrow class fields, and `@memoizeOne` (171 uses) becomes `memoize-one` fields. That drops the decorator Babel plugin.
  - Replace react-modal, react-spring 8 and react-lazyload with current equivalents or native `IntersectionObserver`.
  - Remove the polyfills for `IntersectionObserver`, `ResizeObserver` and `URLSearchParams`.
  - Update Testing Library.
- **Verification.** Playwright smoke suite, and no React warnings in the console on any page.

## 6d. Vitest and Storybook

- **Changes.** Move from Jest to Vitest 5. Replace react-styleguidist with Storybook on Vite and port the `ui/*.md` docs that still matter.
- **Verification.** `pnpm test` and `pnpm storybook build` pass in CI.

## 6e. Flow to TypeScript

- **Changes.**
  - Run `flow-to-ts` one directory at a time, leaves first: `lib/Zen`, `models`, `services`, `components/ui`, then each app.
  - Turn on `strict` in `tsconfig.json`, and use `allowJs` until the last directory is converted.
  - Replace the 103 vendored flow-typed libdefs with the npm `@types/*` packages or the libraries' own types.
  - Delete the Flow strip plugin once the last file moves.
  - Port `lint/eslint/eslint-plugin-zen` rules to ESLint 10 flat config with typescript-eslint, or drop the ones TypeScript already enforces.
- **Verification.**
  - `pnpm typecheck` is clean for every converted directory before the next one starts.
  - The count of `$FlowFixMe` / `$AllowAny` suppressions converted to `any` is tracked and must go down.

## 6f. Retire runtime-loaded vendor scripts

- **Changes.** Turn the registry entries in `web/client/vendor/registry/index.js` into npm dependencies loaded with dynamic `import()`:
  - html2canvas becomes current `html2canvas-pro`.
  - jsPDF and pptxgenjs move to current versions.
  - zipcelx and file-saver move to current versions or native `Blob` downloads.
  - literallycanvas: replace or remove it. It needs `window.React` exposed.
  - The acorn interpreter: replace it with a sandboxed expression evaluator.

  Plotly and d3 v3 leave in phase 7g.
- **Verification.** Each export format (PDF, PPTX, PNG, CSV, XLSX) produces the same file structure as before, checked by Playwright download tests.
