---
paths:
  - "docker/**"
  - "docker-compose*.yaml"
  - "Makefile"
  - ".github/**"
  - "ci/**"
  - "prod/**"
  - "log/**"
  - "pyproject.toml"
  - "requirements*.txt"
---

These files belong to the **infra** role in the Harmony migration (`docs/modernisation/SPEC.md` section 6). Check ownership with `python3 scripts/agents/ownership.py who <path>`.

Before editing, load `harmony-infra`, `docker-skills:docker-compose-patterns`, `astral:uv` and `harmony-migration-protocol` with the Skill tool, unless they are already loaded.

Only nginx is published in production overlays. There are no default secrets. Pin images, actions and downloads. Load `docker-skills:docker-destructive-guardrails` before removing containers, volumes or images.
