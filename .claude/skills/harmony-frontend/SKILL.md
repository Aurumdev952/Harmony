---
name: harmony-frontend
description: Harmony's frontend platform migration, from webpack, Flow, React 16, jQuery, bluebird and Relay to Vite 8, TypeScript 6, React 19, fetch, TanStack Query with a hey-api client, TanStack Router and a PWA. Use when touching web/client outside the design and visualization areas, build config, package.json, tests, entry points, services, models or the page bootstrap. Load the reference file for the area you are working in.
---

# Harmony frontend platform

The codebase today:
- 19 webpack entries in `web/client/entryPoints/`, one per Jinja template.
- Flow on 1,802 files.
- Zen immutable models (`web/client/lib/Zen`).
- `APIService` wraps `$.ajax` in bluebird promises.
- Relay pinned to an experimental build, talking to Hasura.
- `I18N.text` translations.
- Server data passed in through `window.__JSON_FROM_BACKEND`.

The target is in `docs/modernisation/03-target-architecture.md#frontend`, and the requirements are FE-1 to FE-12 in SPEC.

## Reference files

Load only the one the task needs:

| Working on | Read |
|---|---|
| Vite config, entries, manifest, dev server, Babel pass, aliases | [references/vite.md](references/vite.md) |
| React 19 upgrade, `createRoot`, `defaultProps`, decorators | [references/react19.md](references/react19.md) |
| Flow to TypeScript, tsconfig, ESLint 10 | [references/typescript.md](references/typescript.md) |
| API calls, generated client, TanStack Query and Router, the Relay removal | [references/data-layer.md](references/data-layer.md) |
| Vitest, Testing Library, Storybook | [references/testing.md](references/testing.md) |
| Zen models, I18N, `$ref`, `__JSON_FROM_BACKEND`, the vendor registry | [references/legacy-codebase.md](references/legacy-codebase.md) |

For routing, load the vendored `router-core`, `router-plugin` and `router-query` skills. For PWA work, read https://vite-pwa-org.netlify.app/llms.txt.

## Rules

- **Preserve behaviour.** Platform WPs (phase 6) change no pixels. Run the Playwright smoke suite and screenshot the pages you touched before and after.
- **Use codemods for sweeps.** Write a script for any edit that repeats across more than about 10 files: decorators, `ReactDOM.render`, bluebird, `@vx` to `@visx`, Flow to TypeScript. Commit the script under `scripts/codemods/` (a shared path) and run it one directory at a time, checking each.
- **Respect ownership.**
  - `web/client/components/**` belongs to frontend-design.
  - `components/visualizations/**`, `components/ui/visualizations/**` and `components/QueryResult/**` belong to visualization.
  - Request changes there, or coordinate a codemod run with the owner, who runs it in their WP.
- **No new Flow, no new decorators, no new jQuery, bluebird or moment imports,** anywhere.
- **Version facts change fast.** Check `npm view <pkg> version` and the package's migration guide before you rely on any API detail in the references.

## Checks

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm e2e --grep @smoke
```

Then run `verify` on every page the change touches, at 390, 1024 and 1440 pixels wide.
