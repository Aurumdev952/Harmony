# Data layer: generated client, TanStack Query and Router

Sources: https://heyapi.dev/llms.txt, https://tanstack.com/query/latest/llms.txt and the vendored `router-query` skill.

## Today

- **REST (Potion, `/api2`).** `web/client/services/APIService.js` and `web/client/util/ZenClient.js` call `$.ajax`, wrapped in bluebird with cancellation. 136 files import bluebird.
- **GraphQL (Hasura).** Relay calls go through `/api/graphql` in 77 files, with 33 `__generated__` folders. Heavy users are DataCatalogApp, FieldSetupApp, DataUploadApp, the AQT form panel and `patchFieldService.js`.
- **Potion conventions in the client.**
  - `$uri` and `$ref` (31 files).
  - `convertURIToID` / `convertIDToURI` (`web/client/services/wip/util.js:11-30`).
  - `where=` JSON filters (19 files).

## WP-6a: fetch first

- Rewrite `APIService` and `ZenClient` on `fetch`, with `AbortController`, typed errors and JSON parsing, keeping their public methods.
- Replace bluebird by codemod:
  - `Promise` from bluebird becomes native.
  - `.cancel()` becomes an `AbortSignal` passed through.
  - `Promise.map` and `Promise.each` become `Promise.all` with explicit concurrency where it matters (`p-limit`).
- Remove jQuery from `layout.html` once `fetchGeoJsonTiles.js` moves too.

## The generated client (contract C-4)

- `@hey-api/openapi-ts`, **pinned to an exact version** (it is pre-1.0), with the `@tanstack/react-query` plugin. Output goes to `web/client/api/generated/`, which nobody edits.
- Set base URL, credentials (`include`) and CSRF headers in a `createClientConfig()` export referenced by `runtimeConfigPath`. Never edit `client.gen.ts`.
- Use the generated `getXOptions()`, `xMutation()` and `getXQueryKey()`. Spread them into `useQuery` and `useMutation`. Never hand-write a query key for a generated endpoint.

## TanStack Query v5 facts

- Calls take a single options object.
- `isPending` replaces `isLoading` for "no data yet".
- `gcTime` replaces `cacheTime`.
- `placeholderData: keepPreviousData` replaces `keepPreviousData: true`.
- `useQuery` has no `onSuccess` or `onError`. React in effects, or in mutation callbacks.
- Infinite queries need `initialPageParam`.

## Migrating a domain off Potion or Relay (with backend, per WP-5x)

1. The backend lands the FastAPI router and regenerates the client in the same stack.
2. Replace the service calls and Relay hooks for that domain with generated hooks.
3. Delete:
   - the old service functions,
   - `__generated__` folders, `graphql` tags and fragments,
   - `convertURIToID` call sites.
4. Run the domain's Playwright flows and contract cases.

When the last Relay user moves (WP-5e), delete:
- `react-relay` and `relay-runtime`;
- `relay-compiler` and `babel-plugin-relay`;
- `relay.config.js` and `web/client/util/graphql/`.

## Router and single-page app (WP-7f)

- **Router context.** TanStack Router holds `queryClient` in its context. Loaders call `queryClient.ensureQueryData(...)`. Set `defaultPreloadStaleTime: 0` so the router defers caching to Query.
- **Routes.** Keep every old URL (`/advanced-query`, `/dashboard/<slug>`, `/data-catalog/...`, `/embed/...` and so on) as a route. The URL table in `e2e/` is the check.
- **Bootstrap.** `window.__JSON_FROM_BACKEND` (79 files read it) becomes the `/api/v3/session/bootstrap` query, read through a typed `useBootstrap()` hook.
