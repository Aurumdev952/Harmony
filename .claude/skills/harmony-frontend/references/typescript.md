# Flow to TypeScript in Harmony

Also load `pstack:typescript-best-practices`.

## Versions

- **`typescript` stays on 6.x** (`npm:@typescript/typescript6@^6` if 7 becomes the npm default). typescript-eslint needs the TypeScript 6 programmatic API.
- **TypeScript 7** (the native Go compiler, `tsgo`) has no programmatic API. It MAY run as an extra fast `pnpm typecheck:fast` once the codebase is converted.
- **Avoid options TypeScript 7 removes:** `baseUrl`, `moduleResolution: node`, `target: es5`, `esModuleInterop: false`. Use `moduleResolution: "bundler"` and `paths` for the bare-import aliases.

## Conversion order (WP-6e)

Go leaves first, so every converted file only imports converted or `allowJs` files:
1. `web/client/lib/Zen`
2. `web/client/util`
3. `web/client/models`
4. `web/client/services`
5. `web/client/components/ui` (with frontend-design)
6. `web/client/components/visualizations` (with visualization)
7. each app, smallest first.

How to convert:
- Run `flow-to-ts` per directory, then fix by hand.
- `pnpm typecheck` must be clean for the directory before the next one starts.
- Map the Flow suppressions (`$FlowFixMe`, `$AllowAny`, `$FlowTODO`, `$Cast`) to `any` with a `// TODO(WP-6e)` comment, and count them in the WP log. The count must fall over time.
- Map Flow exact objects (`exact_by_default=true` in `.flowconfig`) to plain TypeScript object types. Do not try to imitate exactness.
- Replace the vendored flow-typed libdefs (`web/public/js/vendor/flow-typed`, 103 files) with the libraries' own types or `@types/*`, then delete them.

## Settings

- `strict: true`, `noUncheckedIndexedAccess: true`, `verbatimModuleSyntax: true`, `isolatedModules: true`.
- `allowJs` stays on until the last directory is converted, then comes off.

## ESLint 10

- ESLint 10 removed `.eslintrc`. Use flat config in `eslint.config.js` with typescript-eslint, react-hooks and jsx-a11y.
- Port the rules from `lint/eslint/eslint-plugin-zen` that TypeScript does not already enforce. Delete the rest.
- `eslint-import-resolver-webpack` goes away. Imports resolve through the TypeScript resolver.
