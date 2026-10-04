---
name: harmony-review
description: The code review procedure for Harmony migration work packages, covering correctness, conformance to SPEC requirements and contracts, migrate-then-delete completeness, simplicity and readability. Use when asked to review a WP branch or PR, or to give the reviewer verdict in a WP file.
---

# Reviewing a Harmony work package

You judge the diff. You do not edit production code. The verdict goes in the WP file. Security review is a separate role (`harmony-security`), but report any security issue you notice.

## Procedure

1. Read the WP file (requirements, contracts, units, log, evidence), the WP's row in SPEC section 5, and its phase file.
2. Read the diff: `git diff main...<branch>`. Read the surrounding code for every hunk you judge. Never judge a hunk in isolation.
3. Check ownership: `python3 scripts/agents/ownership.py check --role <owner_role> --head <branch>`.
4. Run a correctness pass with `pstack:interrogate` on contested or cross-cutting WPs: contracts C-1 to C-11, auth, `$ref` migration, Druid upgrade, the single-page-app switch. For the rest, run the built-in `code-review` at high effort on the branch diff.
5. Apply the checklist below.
6. Verify each finding before reporting it. State the input, the wrong result and the line. Drop what you cannot make concrete.
7. Write the verdict:
   - `approved`;
   - `changes-requested` with numbered findings, most severe first;
   - `blocked` when a human decision is needed.

## Checklist

- **Requirements.** Each requirement ID listed in the WP is demonstrably met. Evidence exists and matches the claim.
- **Invariants.** INV-1 to INV-8 hold. Any changed query output or authorisation result is recorded and justified.
- **Contracts.** Changes to C-1 to C-11 follow SPEC 7.4: written note, consumer acknowledgements, producer and consumers in the same stack.
- **Migrate, then delete.** The old path is gone: Potion resource, frontend service, `ui/` wrapper, SCSS partial, Flow file, dependency. A compatibility layer is acceptable only if the spec names it (the `$ref` reader until WP-5g).
- **Subtraction.** No speculative options, layers or wrappers with one caller. No dead code left behind. Prefer the smaller diff that meets the requirement (`pstack:principle-laziness-protocol`).
- **Types.** Boundaries parse external data (Pydantic, generated client types). Internals trust their types. Illegal states are unrepresentable where cheap.
- **Tests.** Bug fixes come with a test that failed first. Tests check behaviour, not implementation. No test was weakened to pass.
- **Comments.** No narrating comments and no commented-out code (`/no-comments`). Comments explain only a non-obvious why.
- **Stack conventions.** The rules in the area's skill (`harmony-query-engine`, `harmony-fastapi`, `harmony-frontend`, `harmony-design-system` and so on) are followed. For design work, also check the `frontend-design:frontend-design` criteria and token-only styling.
- **Commits.** Commits are small, tell the story in order, carry the WP id in the subject, and have no unrelated changes.
