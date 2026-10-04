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
- **Host load** is shared with other agents' stacks (load ~20 seen). Stop idle stacks and tell the lead which projects/ports are yours.

Related: [[druid-version-facts]]
