# Harmony

Harmony is Zenysis's analytics platform for ministries of health. It has a data pipeline into Apache Druid, a Flask web app, and a React frontend. Each country deployment lives in `config/<code>/` and `pipeline/<code>/`, selected by `ZEN_ENV`.

## Modernisation in progress

The codebase is being migrated:
- Flask to FastAPI;
- webpack, Flow and React 16 to Vite, TypeScript and React 19;
- a redesign on HeroUI v3 with Urbanist;
- Druid 0.23 to 37/38, plus a Polars and Dagster pipeline.

- **The binding guide** is `docs/modernisation/SPEC.md`: invariants, requirements, contracts, work packages, path ownership, protocol and definition of done. Read it before changing code.
- **The team:** agent roles, the skills each one loads, and how to run them are in `docs/modernisation/TEAM.md`.
- **Work-package state** lives in `docs/modernisation/work/WP-*.md`, one file per WP.

## Always

- Keep every deployment working (SPEC INV-1). Query results (INV-2) and authorisation decisions (INV-3) never change silently.
- Respect path ownership. Check a path with `python3 scripts/agents/ownership.py who <path>`. Migration agents are blocked by a hook when they edit outside their role.
- Work on `mig/WP-<id>-<slug>` branches in worktrees. Never commit to `main`, force-push, merge, deploy, or read `.env`.
- Any bug fix starts with a failing test. Every user-visible change is checked in the running app (`verify`).

## Team tooling

```bash
python3 scripts/agents/check_team.py            # agents, skills, roles and links are consistent
python3 scripts/agents/task_gate.py WP-<id>     # can this WP close?
scripts/agents/install_plugins.sh               # install the plugins the team's skills come from
scripts/agents/update_vendored_skills.sh        # refresh vendor skills copied into .claude/skills
```
