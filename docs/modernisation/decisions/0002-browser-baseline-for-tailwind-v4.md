# 0002. Browser baseline for Tailwind CSS v4 (phase 7 gate)

Status: **awaiting measurement.** A human with access to a production host fills in the Measurement section, then picks the decision. This file is the "phase 7 decision log" entry that phase 0g asks for.

## Context

Phase 7 moves the UI to HeroUI v3 on Tailwind CSS v4, which needs Chrome 111, Safari 16.4 or Firefox 128 or newer. Nobody has measured which browsers ministry workstations run. Phase 0g ([phase-0-security-and-subtraction.md](../phase-0-security-and-subtraction.md)) sets the gate: if more than 5% of sessions fall below that line, phase 7 needs a fallback plan before it starts.

WP-0g delivered the measuring tool, `prod/browser_share/browser_share.py`. The repository holds no production logs, so an agent cannot run it.

## How to measure

On one deployment's production host, as a user who can read the nginx logs:

1. Get the access logs. In the Docker deployments nginx-proxy logs to the container's stdout, and the json-file driver keeps about 100 MB (10 files of 10 MB):
   ```bash
   docker logs <nginx container> 2>/dev/null > /tmp/<code>-access.log
   ```
   If the host writes log files instead, use them directly, plain or `.gz`, as many as cover the period.
2. Run the script with the deployment code. It needs only `uv` and Python's standard library, and it never prints client addresses:
   ```bash
   uv run prod/browser_share/browser_share.py --deployment <code> /tmp/<code>-access.log
   ```
   Add `--json` for machine-readable output. Delete the copied log afterwards.
3. Paste the output below and fill in the table.

A session is one (client address, user agent) pair with no gap over 30 minutes. If the deployment sits behind another proxy or a shared NAT, all users can share one address, which merges sessions that use the same browser. Note that under Measurement if it applies.

## Measurement

| Field | Value |
|---|---|
| Deployment code | _to fill_ |
| Log period (first and last date) | _to fill_ |
| Sessions counted | _to fill_ |
| Automated requests and unparsed lines excluded | _to fill_ |
| **Sessions below Chrome 111, Safari 16.4 or Firefox 128** | _to fill_ % |
| Sessions with an unknown engine | _to fill_ % |
| Proxy or NAT in front of nginx (yes or no) | _to fill_ |
| Measured by and on (date) | _to fill_ |

Script output:

```text
<paste the full output of browser_share.py here>
```

## Options

- **A. At or below 5%: go ahead with Tailwind v4.** Phase 7 starts as planned. Users below the line get a "supported browsers" notice.
- **B. Above 5%: fallback plan first.** Name the browsers involved from the table above, then choose one before phase 7 starts. For example: a browser upgrade drive with the ministry IT team, with a date; or keep the current UI for those users until a re-measurement shows 5% or less.

## Decision

_To fill after measurement: A or B, with the reason. For B, name the fallback and when to measure again._

## Consequences

_To fill: what phase 7 does differently, if anything, and who owns the follow-up._
