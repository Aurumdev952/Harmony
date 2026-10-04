---
name: harmony-security
description: Harmony's threat model and the security review procedure for migration work packages. Use when reviewing any WP marked Sec in SPEC section 5, any change to authentication, sessions, tokens, permissions, query policies, uploads, exports, Docker/nginx/CI configuration or dependencies, or when asked for a security verdict.
---

# Security review for Harmony

You review. You do not fix production code. Findings go into the WP file's Verdicts row and a `## Security review` section with file:line, the failure scenario, its severity and the fix you require.

## What Harmony protects

- Health programme data, sometimes at facility level.
- Per-user query policies that restrict which geographies a user can see. This is row-level security in Druid filters.
- Admin control of users, roles and groups.
- Deployments run inside ministries, sometimes on networks with weak perimeter controls, so assume an attacker on the network.

## Threat model (the checklist)

1. **Authentication and sessions** (C-5, SEC-5, SEC-6).
   - The `accessKey` JWT: algorithm pinned to HS256, signature verified, expiry checked, revocation checked for API tokens.
   - During the strangler, Flask and FastAPI accept exactly the same tokens.
   - No fallback that accepts unsigned or expired tokens.
   - `X-Username` / `X-Password` header auth is rate-limited and logged.
   - Reset and invite tokens are hashed, single-use and time-limited.
   - CSRF: double-submit on unsafe methods once cookies are `SameSite=Lax`.
2. **Authorisation parity** (INV-3, SEC-4).
   - Every route ported from Potion keeps its permission check. Compare against `web/server/security/signal_handlers.py:341-381`, `web/server/potion/managers.py` and `web/server/security/permissions.py`.
   - Every query path applies the caller's query policy. That includes raw queries, exports, embedded queries, the render bot and any LLM-facing endpoint.
   - The policy suite (`tests/authz/`) passes, and new routes have deny cases.
3. **Injection.**
   - Druid native JSON is built only through the core builder.
   - Druid SQL is parameterised.
   - SQLAlchemy `text()` takes bound parameters, never f-strings.
   - Jinja autoescape is on. `|safe` is only used on `pass_to_js` serialised through `json.dumps` with `</` escaped.
4. **Hasura while it lives** (SEC-2). An admin secret is set, the port is not published, and the role is derived from the session, never from a client header.
5. **Uploads and exports.**
   - Size limits, type checks and storage outside the web root.
   - No path traversal in `/uploads/<datestamp>/<path>`.
   - No subprocess with user-controlled arguments.
   - The render token is scoped to one resource (SEC-7).
   - No dashboard data sent to third parties (SEC-10).
6. **Secrets and configuration** (SEC-1, SEC-3, SEC-9).
   - No defaults, no secrets in images or logs.
   - Only nginx is published.
   - Druid JavaScript is disabled (SEC-8).
   - Images and Actions are pinned.
   - Containers run as non-root.
7. **Supply chain.** For new or changed dependencies: maintainer, age, install scripts, pinning, licence compatibility with AGPL-3.0.

## Procedure

1. Read the WP file, its requirements, and the diff: `git diff main...<branch>`.
2. Run `python3 scripts/agents/ownership.py check --role <owner_role> --head <branch>`. Edits outside the owner's paths are a finding.
3. Run the tools that fit the change:
   - **`differential-review:differential-review`** on every Sec WP. It is the primary pass.
   - **`static-analysis:semgrep`** on changed Python and TypeScript. Triage results with `fp-check:fp-check` before reporting.
   - **`insecure-defaults:audit`** (a command) on configuration and Compose changes.
   - **`sharp-edges:sharp-edges`** on auth, crypto and token code.
   - **`supply-chain-risk-auditor:supply-chain-risk-auditor`** when `pyproject.toml`, `package.json` or a lockfile changes.
   - The built-in `security-review` command for a second opinion on the whole diff. The `claude-security` plugin's full scan is for a phase boundary, not every WP.
4. Verify each candidate finding before reporting it. Build the failure scenario (input, then wrong output, crash or exposure). Drop anything you cannot make concrete.
5. Write the verdict:
   - `approved` when nothing is high or medium;
   - `changes-requested` with numbered findings;
   - `blocked` when the WP needs a human decision (for example, accepting a changed authorisation outcome).

## Severity

- **High:** data exposure across a query-policy boundary, authentication bypass, remote code execution, secret disclosure.
- **Medium:** missing CSRF on a state-changing route, unpinned image or action, missing rate limit on credential checks.
- **Low:** hardening gaps with no reachable exploit.

High and medium findings block the WP.
