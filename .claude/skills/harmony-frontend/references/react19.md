# React 16.13 to 19 in Harmony

Source: https://react.dev/blog/2024/04/25/react-19-upgrade-guide.md. Start with `npx codemod@latest react/19/migration-recipe`, then fix what it cannot.

## What breaks in Harmony

| Change | Where in Harmony | Action |
|---|---|---|
| `ReactDOM.render` removed | 23 files (entry points, `Toaster`, some modals) | `createRoot(el).render(...)`. Keep the root in a module-level variable when the code re-renders into the same element. |
| `defaultProps` on function components ignored, `propTypes` ignored | 133 files use `defaultProps` | Function components: default parameter values. Class components: `static defaultProps` still works. Leave those until the class is converted. Write a codemod that separates the two cases. |
| String refs, `findDOMNode`, legacy context removed | about 1 file uses string refs | Use `useRef` or `createRef`. |
| `react-dom/test-utils` removed | tests | Import `act` from `react`. |
| `useRef()` needs an argument | hooks | `useRef(null)` |
| `ref` is a plain prop for function components | 5 `forwardRef` sites | New code passes `ref` directly. Old `forwardRef` still works. |
| Render errors are not re-thrown | error boundaries | Report errors through `createRoot(..., { onUncaughtError, onCaughtError })` into the logger. |

## Decorators (WP-6c)

- About 184 files use `@autobind` (624 uses) and `@memoizeOne` (171 uses).
- `@autobind` on a method becomes an arrow class field.
- `@memoizeOne` becomes a field initialised with `memoizeOne(...)`.
- Do this by codemod, one directory at a time. Remove the decorators Babel plugin when no decorator remains.

## Dependencies that must move with React 19

These have to be replaced or upgraded in the same wave:
- react-modal, which goes with WP-7d (HeroUI Modal);
- react-spring 8, react-lazyload, react-day-picker 7, react-color, react-draggable, react-grid-layout (an S3 tarball today; use the upstream release), react-window (current), and `@testing-library/react`.

Check each package's React 19 peer range with `npm view <pkg> peerDependencies`.
