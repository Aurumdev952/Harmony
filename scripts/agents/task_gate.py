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
    out = subprocess.run(['git', '-C', cwd, 'rev-parse', '--show-toplevel'], capture_output=True, text=True, check=True)
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


def problems_for(root: Path, wp: str) -> list[str]:
    path = root / WORK / f'WP-{wp}.md'
    if not path.exists():
        return [f'{path.relative_to(root)} does not exist; claim the WP first (SPEC 7.1)']
    text = path.read_text()
    meta = front_matter(text)
    found = []
    if meta.get('status') not in ('ready', 'done'):
        found.append(f'status is "{meta.get("status")}", expected ready or done')
    v = verdicts(text)
    required = ['qa', 'reviewer'] + (['security'] if meta.get('security_review') == 'true' else [])
    for role in required:
        if v.get(role) != 'approved':
            found.append(f'{role} verdict is "{v.get(role, "missing")}", expected approved')
    branch, role = meta.get('branch', ''), meta.get('owner_role', '')
    if branch and role and (root / OWNERSHIP).exists():
        exists = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', '-q', branch], capture_output=True)
        if exists.returncode != 0:
            found.append(f'branch {branch} not found')
        else:
            check = subprocess.run(
                [sys.executable, str(root / OWNERSHIP), 'check', '--role', role, '--head', branch],
                capture_output=True, text=True, cwd=root,
            )
            if check.returncode != 0:
                found.append('files outside the owner role:\n  ' + check.stdout.strip().replace('\n', '\n  '))
    return found


def main() -> int:
    if len(sys.argv) > 1:
        wp = sys.argv[1].removeprefix('WP-')
        found = problems_for(repo_root('.'), wp)
        print('\n'.join(found) if found else f'WP-{wp} meets the definition of done gates')
        return 1 if found else 0
    event = json.load(sys.stdin)
    m = TOP_LEVEL.match(event.get('task_subject', ''))
    if not m:
        return 0
    found = problems_for(repo_root(event.get('cwd', '.')), m.group(1).lower())
    if not found:
        return 0
    print(f'WP-{m.group(1)} cannot close yet (SPEC section 8):\n- ' + '\n- '.join(found), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
