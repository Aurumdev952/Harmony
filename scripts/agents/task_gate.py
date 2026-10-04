#!/usr/bin/env python3
"""TaskCompleted hook and CLI: a work package closes only when SPEC section 8 is met.

Hook mode (stdin JSON with task_subject): gates tasks whose subject starts with `WP-<id>:`.
Unit tasks (`WP-<id>.<n>: ...`) and other tasks pass through.
CLI mode: task_gate.py WP-<id>   prints the same verdict for a human or the lead.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

WORK = Path('docs/modernisation/work')
OWNERSHIP = Path('scripts/agents/ownership.py')
TOP_LEVEL = re.compile(r'^\s*WP-([0-9]+[a-z])\s*:', re.IGNORECASE)


def repo_root(cwd: str) -> Path:
    out = subprocess.run(
        ['git', '-C', cwd, 'rev-parse', '--show-toplevel'],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def front_matter(text: str) -> dict[str, str]:
    block = text.split('---', 2)[1] if text.startswith('---') else ''
    fields = {}
    for line in block.splitlines():
        m = re.match(r'^([a-z_]+):\s*"?([^"#]*?)"?\s*(#.*)?$', line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def verdicts(text: str) -> dict[str, str]:
    section = text.split('## Verdicts', 1)[1] if '## Verdicts' in text else ''
    rows = {}
    for line in section.splitlines():
        cells = [c.strip().lower() for c in line.strip().strip('|').split('|')]
        if len(cells) >= 2 and cells[0] in ('qa', 'reviewer', 'security'):
            rows[cells[0]] = cells[1]
    return rows


def spec_roles(root: Path, wp: str) -> list[str]:
    """Owner plus supporting roles from the SPEC WP table, e.g. ['backend', 'core', 'infra']."""
    for line in (root / 'docs/modernisation/SPEC.md').read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) >= 5 and cells[0].lower() == wp.lower():
            return [cells[2]] + [
                r.strip()
                for r in cells[3].split(',')
                if r.strip() and r.strip() != 'none'
            ]
    return []


ROLES = 'core|backend|frontend-platform|frontend-design|visualization|data-platform|pipeline|infra|qa'
INSTANCE_DECL = re.compile(rf'^\s*-\s*name:\s*"?({ROLES})-\d+"?', re.M)
LOG_LINE = re.compile(
    rf'^\s*(?:[-*]\s+)?\d{{4}}-\d{{2}}-\d{{2}}\s+({ROLES})-\d+\b', re.M
)


def contributing_roles(text: str) -> list[str]:
    """Roles whose instances the WP file declares (front matter) or that wrote a dated log line."""
    return sorted(set(INSTANCE_DECL.findall(text)) | set(LOG_LINE.findall(text)))


def instance_claims(text: str) -> dict[str, list[str]]:
    """Instance name -> files globs from the front matter's `instances:` block."""
    block = text.split('---', 2)[1] if text.startswith('---') else ''
    claims: dict[str, list[str]] = {}
    current = None
    in_files = False
    for line in block.splitlines():
        stripped = line.strip()
        m = re.match(r'^-\s*name:\s*"?([^"#]+?)"?\s*(#.*)?$', stripped)
        if m:
            current = m.group(1).strip()
            claims[current] = []
            in_files = False
            continue
        if current is None:
            continue
        m = re.match(r'^files:\s*(.*?)\s*(#.*)?$', stripped)
        if m:
            inline = m.group(1).strip()
            if inline.startswith('['):
                claims[current] += [
                    f.strip().strip('"\'')
                    for f in inline.strip('[]').split(',')
                    if f.strip()
                ]
                in_files = False
            else:
                in_files = True
            continue
        if in_files and stripped.startswith('- '):
            claims[current].append(stripped[2:].split('#')[0].strip().strip('"\''))
        elif in_files and stripped and not stripped.startswith('-'):
            in_files = False
    return claims


def claim_problems(root: Path, text: str, base: str, branch: str) -> list[str]:
    """SPEC 7.2: every changed file is claimed by exactly one instance."""
    sys.path.insert(0, str(root / 'scripts' / 'agents'))
    from ownership import glob_to_regex  # noqa: PLC0415

    claims = instance_claims(text)
    if not claims or not any(claims.values()):
        return ['no instance declares files: in the front matter (SPEC 7.2)']
    patterns = {
        name: [glob_to_regex(g) for g in globs] for name, globs in claims.items()
    }
    diff = subprocess.run(
        ['git', '-C', str(root), 'diff', '--name-only', f'{base}...{branch}'],
        capture_output=True,
        text=True,
        check=True,
    )
    uncovered, duplicated = [], []
    for rel in filter(None, diff.stdout.splitlines()):
        if rel.startswith('docs/modernisation/work/') or rel.startswith(
            '.claude/agent-memory/'
        ):
            continue
        owners = [n for n, regs in patterns.items() if any(r.match(rel) for r in regs)]
        if not owners:
            uncovered.append(rel)
        elif len(owners) > 1:
            duplicated.append(f'{rel} ({", ".join(owners)})')
    found = []
    if uncovered:
        found.append(
            'changed files no instance claims (SPEC 7.2):\n  ' + '\n  '.join(uncovered)
        )
    if duplicated:
        found.append(
            'files claimed by more than one instance (SPEC 7.2):\n  '
            + '\n  '.join(duplicated)
        )
    return found


def problems_for(root: Path, wp: str) -> list[str]:
    path = root / WORK / f'WP-{wp}.md'
    if not path.exists():
        return [
            f'{path.relative_to(root)} does not exist; claim the WP first (SPEC 7.1)'
        ]
    text = path.read_text()
    meta = front_matter(text)
    found = []
    if meta.get('status') not in ('ready', 'done'):
        found.append(f'status is "{meta.get("status")}", expected ready or done')
    v = verdicts(text)
    required = ['qa', 'reviewer'] + (
        ['security'] if meta.get('security_review') == 'true' else []
    )
    for role in required:
        if v.get(role) != 'approved':
            found.append(
                f'{role} verdict is "{v.get(role, "missing")}", expected approved'
            )
    branch, role = meta.get('branch', ''), meta.get('owner_role', '')
    if branch and role and (root / OWNERSHIP).exists():
        exists = subprocess.run(
            ['git', '-C', str(root), 'rev-parse', '--verify', '-q', branch],
            capture_output=True,
        )
        if exists.returncode != 0:
            found.append(f'branch {branch} not found')
        else:
            roles = spec_roles(root, wp) or [role]
            if role not in roles:
                roles.insert(0, role)
            roles += [r for r in contributing_roles(text) if r not in roles]
            role_args = [arg for r in roles for arg in ('--role', r)]
            check = subprocess.run(
                [
                    sys.executable,
                    str(root / OWNERSHIP),
                    'check',
                    *role_args,
                    '--head',
                    branch,
                ],
                capture_output=True,
                text=True,
                cwd=root,
            )
            if check.returncode != 0:
                found.append(
                    'files outside the owner role:\n  '
                    + check.stdout.strip().replace('\n', '\n  ')
                )
            base = (
                subprocess.run(
                    [sys.executable, str(root / OWNERSHIP), 'base'],
                    capture_output=True,
                    text=True,
                    cwd=root,
                ).stdout.strip()
                or 'main'
            )
            found += claim_problems(root, text, base, branch)
    return found


def main() -> int:
    if len(sys.argv) > 1:
        wp = sys.argv[1].removeprefix('WP-')
        found = problems_for(repo_root('.'), wp)
        print(
            '\n'.join(found) if found else f'WP-{wp} meets the definition of done gates'
        )
        return 1 if found else 0
    event = json.load(sys.stdin)
    m = TOP_LEVEL.match(event.get('task_subject', ''))
    if not m:
        return 0
    found = problems_for(repo_root(event.get('cwd', '.')), m.group(1).lower())
    if not found:
        return 0
    print(
        f'WP-{m.group(1)} cannot close yet (SPEC section 8):\n- ' + '\n- '.join(found),
        file=sys.stderr,
    )
    return 2


if __name__ == '__main__':
    sys.exit(main())
