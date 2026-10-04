---
name: druid-version-facts
description: Verified Druid 32/38 facts that contradict or refine the harmony-druid skill (ZooKeeper still needed in 38, legacy null flags fatal from 32)
metadata:
  type: reference
---

Checked against https://druid.apache.org/docs/latest/release-info/upgrade-notes on 2026-10-04 (page covers 38.0.0):

- **ZooKeeper is still required in 38.** 38 removed the ZooKeeper task runner (`druid.indexer.runner.type=remote`) and ZooKeeper segment announcement, but "ZooKeeper is still used for Coordinator/Overlord leader election and service (node) announcement and discovery". The harmony-druid skill's "drop ZooKeeper (38)" is wrong; WP-8b must keep ZooKeeper in Compose.
- 32.0.0: `useDefaultValueForNull=true`, `useStrictBooleans=false`, `useThreeValueLogicForNativeFilters=false` make services refuse to start.
- 32.0.0 notes JavaScript filters do not work on Java 17; another reason JavaScript must go before 8b.
- `apache/druid:38.0.0` ships Temurin Java 21.0.10. Extraction functions (timeFormat, lookup map, cascade) still work on 38; verified live in WP-8a.
- The Zenysis `druid-aggregatable-first-last` extension (aggregateLast) exists for 0.23 only and NPEs under SQL-compatible nulls even on 0.23.

Related: [[null-audit-host-traps]]
