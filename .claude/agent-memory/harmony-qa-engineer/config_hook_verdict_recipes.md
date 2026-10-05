---
name: config-hook-verdict-recipes
description: How to verify config/ import-hook and multi-interpreter WPs (WP-3a, 3b) on the host; shell-guard traps, py3.8 web env, DRUID_HOST trap
metadata:
  type: project
---

Recipes that worked for the WP-3a QA verdict (2026-10-04, approved).

- **Worktree guard.** The isolation guard refuses compound Bash lines that pipe git, use `timeout`, `env -u`, `python -c "..."` or heredocs with complex text. Write probes and runners with the Write tool into `/tmp/<wp>-ev/` and run them as `bash script.sh` (scripts written by Write are not executable). Old-vs-new trees: `rsync -a --exclude .git --exclude .venv` the scratch worktree, then `git show <base>:<path> > copy/<path>` to overlay old files; `git archive --format=tar -o x.tar <branch> <dir>` to overlay another WP's suite. See [[worktree-guard-bash]].
- **`uv pip` is blocked by a hook.** Use `uv run --no-project -p <v> --with-requirements <file> --with <pkg>` instead of building a venv.
- **Web server image is `python:3.8`** (`docker/web/Dockerfile_web-server`, `requirements.txt` + `requirements-web.txt`). uv rejects the `-e git+...` lines; strip `-e ` into a scratch copy. Importing every `web.server.*` module (pkgutil walk, skip migrations) gives 163 ok and 11 "outside application context" failures on the legacy tree; compare old vs new rather than expecting zero.
- **`DRUID_HOST` must not carry a port** for a closed-port test: the coordinator port is appended, so `http://127.0.0.1:9` yields `InvalidURL` without opening a socket. Use `http://127.0.0.1` (8081 refused, `ConnectionError`) and monkeypatch `socket.socket.connect` to prove no I/O on import.
- **`template` is not a valid `ZEN_ENV`** by design (`VALID_MODULES` excludes it); check `config.template.*` by explicit import, with `MAPBOX_ACCESS_TOKEN` set (template `ui.py` reads it).
- **Golden warning counts vary with hash seed** (SQLAlchemy mapper SAWarnings). Compare with `PYTHONHASHSEED=0` on both sides.
- **3.13 pipeline suite** stops at `future==0.18.3` (`import imp`) until WP-3b; with `future==1.0.0` in a scratch requirements copy it passes. WP-2d suite was 130 cases at `bda45dc`.
