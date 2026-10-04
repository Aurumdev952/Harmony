# Frontend tests: Vitest, Testing Library, Storybook

Sources: https://vitest.dev/llms.txt, https://vitest.dev/guide/migration.md, https://storybook.js.org/llms.txt. Also load the `storybook:stories` skill when writing stories.

## Vitest 5 facts

- Node 22.12 or later is required (Harmony uses 24).
- `vite` is a peer dependency.
- `clearMocks` defaults to true.
- `vi.mock` inside a `describe` block throws. Keep mocks at module top level.
- An `expect(...).resolves` that isn't awaited fails the test.
- `test.sequential` is removed.
- Browser-mode locators are strict.

## Where tests live

- Unit tests sit next to the code: `Foo.test.ts(x)`. The owner of the code writes them.
- Cross-cutting suites (`e2e/`, `tests/`) belong to QA.
- Every bug fix starts with a failing test (QA-1).

## What to test in the platform migration

- The Zen model serialisers (`serializeForQuery`, `$ref` handling) before and after TypeScript conversion.
- `APIService` errors, cancellation and JSON parsing.
- Date utilities, including the Ethiopian calendar (`web/client/components/ui/DatePicker`, `ethiopianDateUtil`).
- Generated-client wrappers: one test per custom `createClientConfig` behaviour (credentials, CSRF header, error mapping).

## Storybook

- Storybook 10 runs on Vite. It replaces react-styleguidist (`web/client/styleguide/styleguide.config.js`).
- Add `@storybook/addon-mcp` (with `features.componentsManifest: true`) when Storybook lands in WP-6d. It gives agents a component manifest over MCP at `localhost:6006/mcp`. Register it in `.mcp.json` through the lead.
- Every HeroUI-based primitive gets a story with interaction tests: keyboard, focus and disabled state.
