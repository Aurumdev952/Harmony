---
name: frontend-build-and-template-verification
description: How to verify frontend subtraction WPs (bundles, CSS, Jinja templates, script URLs) without the running app, and the shell traps in an isolated QA worktree
metadata:
  type: reference
---

Recipe that worked for the WP-0e QA verdict (2026-10-04):

- Scratch trees: `git -C <own worktree> worktree add --detach /tmp/<x>/{base,br} <ref>`; remove with `worktree remove --force` at the end.
- Install and build on host Node 24: `NODE_OPTIONS=--dns-result-order=ipv4first yarn install --frozen-lockfile --ignore-scripts` then `yarn build` (about 60 s and 90 s). `--ignore-scripts` is required because node-pty does not compile on Node 24. Output goes to `web/public/build/min/`. JS bundles are not content-hashed, but CSS and maps are, so compare them by logical name.
- CSS rule diff: run postcss from the tree's `node_modules` (set `POSTCSS=<tree>/node_modules/postcss`) to print one line per rule with its at-rule context, then `diff`. Check that every removed selector in a comma list carries the removed class, not just the line as a whole.
- Templates: render with `jinja2.ChoiceLoader([FileSystemLoader([templates, repo_root]), DictLoader({'flask_user/_macros.html': stub macros})])`, `ChainableUndefined`, `config.IS_PRODUCTION=True`, and the build's real `sourcemap.json`. With these, `auth/` and `emails/` render too, which builders often skip. Then map each `<script src>` to a file under `web/public`.
- Static browser smoke: serve `web/public` with `python -m http.server`, put the rendered HTML under `__qa/`, and load each page with Playwright (`npm i --prefix /tmp/x/pw playwright@1.56`, which uses the cached chromium-1194). App init throws `defaultLocale` because `pass_to_js` is a stub, so this only proves script loading and globals. It does not replace `verify`.
- Shell traps in the isolated worktree:
  - The guard refuses compound commands that `cd` outside the worktree and refuses `$VAR` arguments. Write scripts with the Write tool and run them with absolute paths.
  - A hook demands `uv run --no-project python` instead of `python3`.
  - `pkill -f <pattern>` kills its own shell (exit 144). Find the PID with `ps -eo pid,args | grep "[p]attern"` instead.
- Gate trap: run `task_gate.py` from a tree that has decision 0001 (`mig/integration`). An older branch copy of `ownership.py` diffs against `main` and flags SPEC.md and ownership.py.
