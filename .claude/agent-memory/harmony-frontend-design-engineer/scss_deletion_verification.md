---
name: scss-deletion-verification
description: How to prove an SCSS deletion only removes the intended rules (postcss rule diff), plus worktree-isolation Bash traps
metadata:
  type: project
---

Prove an SCSS deletion with a rule-level diff, not a byte diff. Minified CSS is one line, so a byte diff tells you nothing.
- Build before and after with `yarn build`. The CSS lands in `web/public/build/min/bundle.<hash>.css`. Install with `yarn install --frozen-lockfile --ignore-scripts` on Node 24; the first build takes about 2.5 min, later ones about 1 min.
- Parse each CSS file with `node_modules/postcss` into one line per rule, with its at-rule context. Then check: the after-list is the before-list minus the removed rules, in the same order; nothing is added; every removed rule names the target classes. The JS bundles must stay byte-identical.

**Why:** reviewers on WP-0e (R5, 2026-10-04) needed proof that "the CSS differs from main only by the removed rules". The rule diff gives them that in a few lines.

**How to apply:** use this for any wave in WP-7e or 7h that deletes SCSS.
- If the base branch has the same `web/public/scss` and webpack configs as `main` (`git diff main -- ...` is empty), the base build stands in for main's.
- Trap: a worktree-isolated agent's Bash refuses long compound commands with heredocs. Write the script to /tmp with the Write tool, then run it in a single plain command.
- Trap: in `grep -v`, filter case-sensitively. `-viE DatePicker` also hides the lowercase `datepicker` class hits you are looking for.
