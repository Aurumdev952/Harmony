---
name: template-render-diff
description: How to prove a Jinja template edit under web/server/templates changes only what you intended, without a running Flask app (which needs live Druid)
metadata:
  type: reference
---

The Flask app cannot boot without a live Druid datasource, so `verify` on pages is often unavailable. For template-only changes, render every template before and after and run `diff -r` on the output:

- `jinja2.Environment(loader=FileSystemLoader("web/server/templates"), undefined=<ChainableUndefined subclass whose __call__ returns a marker string>, extensions=[i18n, do, loopcontrols])`, then `install_null_translations()`.
- Stub `get_flashed_messages` as a global returning `[]`, or `layout.html` fails with "not enough values to unpack".
- Render each template with `is_screenshot_request` both False and True.
- Six `emails/*` templates and `auth/user_profile.html` always fail to render this way (repo-root include paths, `flask_user/_macros.html`). Treat that as a baseline and ignore it.
- Run with `uv run --no-project --with jinja2 python <script> . <outdir>`. Keep the script in /tmp, not in the worktree.

The worktree-isolation guard refuses Bash that mixes `cd`, shell variables and `sed -i` in loops. Use the Edit tool for doc edits, or plain single commands.
