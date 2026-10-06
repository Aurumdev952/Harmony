# 0007. WP-8b constraints: ZooKeeper stays, Druid authentication, closed ports, JavaScript off

Status: applied by the lead on 2026-10-05, pending human ratification (SPEC section 10).

## Context

WP-8a (Druid JavaScript removal and null audit) and its security review established facts the phase-8 plan did not have:

- **ZooKeeper.** The Druid 38 upgrade notes still require ZooKeeper for leader election and service discovery on a standalone cluster; only the Kubernetes discovery extension removes it. The phase-8 text ("Drop ZooKeeper if targeting 38") and the `harmony-druid` skill were wrong on this point.
- **Druid is unauthenticated and published.** `druid_setup/` publishes every Druid, ZooKeeper, memcached and Postgres port on all interfaces, uses `postgres:latest` and a hard-coded metadata password. WP-0b's bind-address ruling has not reached it. Anonymous access to the router, broker and coordinator includes the SQL endpoint, task submission and the properties page.
- **LAST_VALUE.** The Zenysis `aggregateLast` extension throws under SQL-compatible nulls and does not exist for Druid 38. WP-8a added a native expression aggregator behind `HARMONY_DRUID_LAST_VALUE`, defaulting to `extension` until the upgrade, with one Low fix pending (explicit accumulator name).
- **JavaScript.** WP-8a turns `druid_javascript_enabled` off and removes every JavaScript construct; nothing pins that permanently yet.
- **Extensions and images.** `druid_setup/extensions/load_extensions.sh` fetches extensions from `master` with no checksum; audit images are pinned by tag only.

## Decision

WP-8b (Druid 37/38 on Java 21; owner data-platform, supporting infra, Sec yes) carries these as requirements, each with a failing test first:

1. **ZooKeeper stays** in the single and cluster Compose files, pinned by digest, on the internal network only; the phase-8 text and the `harmony-druid` skill are corrected.
2. **Authentication.** Druid's `druid-basic-security` extension with an internal escalator; query-client, pipeline and admin credentials come from secrets (WP-0b's refusal of default secrets applies); anonymous access to router, broker, coordinator, overlord and historical is denied, including `/druid/v2/sql`, task submission and `/status/properties`. The web app and pipeline read the credentials through `harmony.core.settings` (WP-4a).
3. **Closed ports.** No Druid, ZooKeeper, memcached or Postgres port is published; the router is reached through the Compose network only; `postgres` pinned by digest with a required password.
4. **JavaScript off for good.** A permanent test fails if any `druid_setup` env enables JavaScript or any builder or fixture emits a `javascript` type.
5. **LAST_VALUE native everywhere.** `HARMONY_DRUID_LAST_VALUE` defaults to `native`, the extension branch and the first-last extension are deleted from code and `loadList`, after the `__acc` accumulator fix; proven byte-identical on the golden suite.
6. **Pinned supply chain.** Extension downloads pinned to a release and checksum (or vendored); every image in `druid_setup` pinned by digest; containers run without root.
7. **Re-run the policy probe** from the WP-8a security review on the upgraded Druid (three-valued logic is then the only mode), including a policy shape that *includes* `''`: WP-8a's second security pass found such a policy is posted as `in [""]` untranslated, so on Druid 38 it hides null rows the current Druid shows (fails closed); if any deployment has one, a human accepts the change or backend translates `''` to null in the policy builder (the builder is backend's; corrected by decision 0014). The Druid 38 harness image is recorded by digest in the run instructions. Carry N0 (no-value dimensions are stored as null, never `''`) into the WP-8c Parquet schema contract.

## Consequences

- SPEC 1.7: 8b row unchanged; phase 8 section 8b amended; `harmony-druid` skill corrected.
- Druid authentication, the lead-decision candidate from WP-0b, is settled by rule 2.
