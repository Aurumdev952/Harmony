# 0014. WP-8b: Druid network topology and policies that include the empty string

Status: applied by the lead on 2026-10-06, pending human ratification (SPEC section 10).

## Context

WP-8b (Druid 38 on Java 21, branch `mig/WP-8b-druid-38` at aed3c8a) implements decision 0007: ZooKeeper kept, `druid-basic-security` with an internal escalator and per-role users, images by digest, non-root, JavaScript off, extensions pinned. Its live runs raised three questions the builder could not settle:

- **Q1.** Cluster mode spans three hosts; Druid processes must reach each other, so "no published port" (decision 0007 rule 3) cannot hold across hosts with plain Docker networking. The branch binds the ports to private addresses behind authentication.
- **Q2.** Single mode now publishes nothing and attaches only the router to a shared Docker network `harmony_druid`, so web, worker, pipeline and Druid must share one Docker host.
- **Q3.** On Druid 38 a query policy that *includes* `''` fails closed (hides the no-value rows that 0.23 showed), confirmed by the committed policy probe (8 identities, 0 leaks, 0 wider access). Decision 0007 rule 7 left the choice between accepting that and translating `''` to null in the policy builder, which lives in backend's `web/server/routes/views/query_policy.py`, not core's as 0007 assumed.

## Decision

1. **Q1, cluster mode.** Accepted as a recorded residual for this WP: Druid ports bound to private addresses, reachable only inside the deployment's private network, every endpoint authenticated, anonymous access denied. An encrypted overlay (Docker Swarm overlay with encryption, or WireGuard between the hosts) is the remedy, owned by infra as a WP-8b follow-up (`8b-net`), not a blocker. A deployment that runs cluster mode must have the private network documented in its runbook.
2. **Q2, single mode.** Accepted: single mode requires web, worker, pipeline and Druid on one Docker host, which is how every deployment runs today. The WP records it in its README section.
3. **Q3, policies including `''`.** Option (a) with a check: WP-8b ships a read-only query that lists every stored query policy whose filter includes the empty string, run once per deployment before upgrading; if any exists the deployment owner either rewrites it to the null form or asks for option (b). No translation is added to the policy builder. If a deployment reports such policies, the lead opens a backend unit for option (b). The INV-3 row: on Druid 38 an include-`''` policy hides no-value rows it showed on 0.23 (fails closed; nothing becomes visible).
4. **Ownership correction.** Decision 0007 rule 7's "core translates" reads "backend translates" (the builder is backend's).

## Consequences

- WP-8b may go `ready` without the overlay network, with the residual, the single-host constraint, the policy check and the INV-3 row recorded; security rates the residual at the gate.
- Open cross-role requests from WP-8b are dispatched by the lead: core (native LAST_VALUE only; sketch merge off with the INV-2 option (a) note; Druid credentials in `harmony.core.settings` with default refusal and every request through the router), infra (web, worker and pipeline join `harmony_druid`, `DRUID_HOST=http://router`, credentials from secrets), qa (regenerate `calc_last_value` after the native-only change; a golden case for two COUNT_DISTINCT on one dimension), pipeline (delete the dead nested-JSON row writer).
