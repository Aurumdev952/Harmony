---
name: null-audit-host-traps
description: Traps hit running throwaway Druid stacks for scripts/druid/null_audit on this host and in an isolated worktree, with what works
metadata:
  type: feedback
---

Running `scripts/druid/null_audit` (WP-8a) taught these; each cost a retry.

- **Worktree hook.** An isolated agent's Bash is refused for heredocs feeding python, `for` loops with variables, `export X=$(...)`, and `git -C <other worktree>`. **How to apply:** edit with the Edit/Write tools, run plain one-line commands, pass compose settings with `docker compose --env-file /tmp/<file>` (also keeps the throwaway password off command lines).
- **Docker address pools exhausted** ("all predefined address pools have been fully subnetted") once ~4 projects run. **How to apply:** a local override giving the default network an explicit subnet (`10.231.8.0/24` worked), or stop an idle stack.
- **Metadata Postgres reused an anonymous volume** from an earlier run with another password, so the coordinator never became leader (router: "Unable to determine destination"). The compose now puts Postgres data on tmpfs. Druid logs go to `/opt/druid/log/${sys:druid.node.type}.log` inside the container, not to `docker logs`.
- **Waiting for segments:** `loadstatus?full` never reaches 0 with one historical (default rule wants 2 replicas), and the percent view already reads 100 while a reindex is replacing segments. **Why:** both gave false "loaded". **How to apply:** wait until `sys.segments` (published, not overshadowed) has a newer version than before submit and none unavailable. 0.23 SQL has no MAX over strings; compute in Python.
- **Inline datasources** fail with `Integer cannot be cast to Long` for `__time` values near the epoch; ingest a small datasource instead.
- **Resuming after a reboot:** `/tmp/wp8a` (env files with the throwaway password, `out/legacy2` baseline, subnet overrides) and the `wp8a-*` volumes survived; only containers were gone. Re-run `up -d`, wait on `/druid/coordinator/v1/leader` plus `SELECT 1`, then `index` (the metadata store is tmpfs, so always reindex). Run scripts with `PYTHONPATH=.`. Give each concurrent project its own subnet override (10.231.8/9/10.0/24 worked).
- **Lint:** the repo pins no ruff or black (`uv run ruff` fails). `uvx ruff` picks up a global config that flags pyupgrade rules on this 3.9 tree, so judge with `--select F,E9`. `uvx black` (24+) wants a blank line after module docstrings, which the repo style lacks; ignore that.
- **Interrogate panel:** the session-wide cap of 20 concurrent subagents can block `pstack:interrogate`. Do a traced lead pass and ask the lead to dispatch the panel.
- **Host load** is shared with other agents' stacks (load ~20 seen). Stop idle stacks and tell the lead which projects/ports are yours.

Related: [[druid-version-facts]]
