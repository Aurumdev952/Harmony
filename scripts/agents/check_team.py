#!/usr/bin/env python3
"""Validates the migration team wiring. Exit 1 on any problem.

Checks: every agent's frontmatter parses; every skill an agent preloads resolves to a project
skill, an installed plugin skill, or a known built-in; every agent maps to an ownership role in
SPEC section 6 (reviewer and security are read-only roles); every project skill's internal links exist.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from ownership import AGENT_ROLES, load_rules, repo_root  # noqa: E402

BUILT_IN_SKILLS = {
    'dataviz',
    'verify',
    'run',
    'code-review',
    'simplify',
    'security-review',
}
READ_ONLY_ROLES = {'reviewer', 'security'}
PLUGIN_ROOT = Path.home() / '.claude' / 'plugins'


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    return yaml.safe_load(text.split('---', 2)[1]) if text.startswith('---') else {}


def plugin_skill_exists(ref: str) -> bool:
    plugin, skill = ref.split(':', 1)
    patterns = [
        f'cache/*/{plugin}/*/skills/{skill}/SKILL.md',
        f'synced/*/{plugin}/skills/{skill}/SKILL.md',
    ]
    if plugin == skill:
        patterns.append(f'cache/*/{plugin}/*/SKILL.md')
    return any(next(PLUGIN_ROOT.glob(p), None) for p in patterns)


def main() -> int:
    root = repo_root(Path.cwd())
    problems: list[str] = []
    local_skills = {p.parent.name for p in (root / '.claude/skills').glob('*/SKILL.md')}
    spec_roles = {role for role, _, _ in load_rules(root)}

    agents = sorted((root / '.claude/agents').glob('*.md'))
    seen = set()
    for path in agents:
        try:
            meta = frontmatter(path)
        except yaml.YAMLError as exc:
            problems.append(
                f'{path.name}: frontmatter does not parse ({exc.__class__.__name__})'
            )
            continue
        name = meta.get('name')
        seen.add(name)
        role = AGENT_ROLES.get(name)
        if role is None:
            problems.append(
                f'{path.name}: {name} missing from AGENT_ROLES in ownership.py'
            )
        elif role not in spec_roles and role not in READ_ONLY_ROLES:
            problems.append(f'{path.name}: role {role} has no row in SPEC section 6')
        for ref in meta.get('skills') or []:
            ok = (
                ref in local_skills
                or ref in BUILT_IN_SKILLS
                or (':' in ref and plugin_skill_exists(ref))
            )
            if not ok:
                problems.append(
                    f'{path.name}: skill {ref} not found (run scripts/agents/install_plugins.sh?)'
                )
    for name in set(AGENT_ROLES) - seen:
        problems.append(
            f'ownership.py maps {name}, but .claude/agents/{name}.md does not exist'
        )

    for skill_md in (root / '.claude/skills').glob('harmony-*/**/*.md'):
        for target in re.findall(r'\]\(([^)#]+)(?:#[^)]*)?\)', skill_md.read_text()):
            if target.startswith('http'):
                continue
            if not (skill_md.parent / target).resolve().exists():
                problems.append(f'{skill_md.relative_to(root)}: broken link {target}')

    for p in problems:
        print(p)
    print(
        f'{len(agents)} agents, {len(local_skills)} project skills, {len(problems)} problems'
    )
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
