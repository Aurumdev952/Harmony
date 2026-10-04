#!/usr/bin/env python3
"""Path ownership for the migration team, read from docs/modernisation/SPEC.md section 6.

Modes:
  ownership.py who PATH...                 print the owning role of each path
  ownership.py check --role ROLE [--base REF] [--head REF]
                                           list files changed in BASE...HEAD that ROLE may not edit
  ownership.py hook                        PreToolUse hook: read the event JSON on stdin and
                                           block Edit/Write by a harmony-* agent outside its paths
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

SPEC = Path('docs/modernisation/SPEC.md')
SHARED = 'shared'

AGENT_ROLES = {
    'harmony-core-engineer': 'core',
    'harmony-backend-engineer': 'backend',
    'harmony-frontend-platform-engineer': 'frontend-platform',
    'harmony-frontend-design-engineer': 'frontend-design',
    'harmony-visualization-engineer': 'visualization',
    'harmony-data-platform-engineer': 'data-platform',
    'harmony-pipeline-engineer': 'pipeline',
    'harmony-infra-engineer': 'infra',
    'harmony-qa-engineer': 'qa',
    'harmony-code-reviewer': 'reviewer',
    'harmony-security-reviewer': 'security',
}


def repo_root(start: Path) -> Path:
    probe = start if start.is_dir() else start.parent
    while not probe.exists():
        probe = probe.parent
    out = subprocess.run(
        ['git', '-C', str(probe), 'rev-parse', '--show-toplevel'],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def glob_to_regex(glob: str) -> re.Pattern[str]:
    out = ''
    i = 0
    while i < len(glob):
        if glob.startswith('**', i):
            out += '.*'
            i += 2
        elif glob[i] == '*':
            out += '[^/]*'
            i += 1
        elif glob[i] == '?':
            out += '[^/]'
            i += 1
        else:
            out += re.escape(glob[i])
            i += 1
    return re.compile(out + r'\Z')


def literal_prefix_len(glob: str) -> int:
    return len(re.split(r'[*?]', glob, maxsplit=1)[0])


@lru_cache(maxsize=None)
def load_rules(root: Path) -> tuple[tuple[str, str, re.Pattern[str]], ...]:
    spec = root / SPEC
    if not spec.exists():
        spec = Path(__file__).resolve().parents[2] / SPEC
    text = spec.read_text()
    block = text.split('<!-- ownership:start -->', 1)[1].split(
        '<!-- ownership:end -->', 1
    )[0]
    rules = []
    for line in block.splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) != 2 or cells[0] in ('Role', '---'):
            continue
        for glob in re.findall(r'`([^`]+)`', cells[1]):
            rules.append((cells[0], glob, glob_to_regex(glob)))
    if not rules:
        sys.exit(f'ownership: no rules found between the markers in {SPEC}')
    return tuple(rules)


def owner_of(root: Path, rel: str) -> str | None:
    best_score, best_role = -1, None
    for role, glob, regex in load_rules(root):
        if not regex.match(rel):
            continue
        score = literal_prefix_len(glob)
        if score > best_score:
            best_score, best_role = score, role
    return best_role


def is_shared(root: Path, rel: str) -> bool:
    return owner_of(root, rel) == SHARED


def may_edit(root: Path, role: str, rel: str) -> tuple[bool, str | None]:
    if is_shared(root, rel):
        return True, SHARED
    owner = owner_of(root, rel)
    return owner == role, owner


def cmd_who(paths: list[str]) -> int:
    for raw in paths:
        path = Path(raw).resolve()
        root = repo_root(path)
        rel = path.relative_to(root).as_posix()
        print(
            f'{rel}\t{"shared" if is_shared(root, rel) else owner_of(root, rel) or "lead (unowned)"}'
        )
    return 0


def default_base() -> str:
    probe = subprocess.run(
        ['git', 'rev-parse', '--verify', '-q', 'mig/integration'], capture_output=True
    )
    return 'mig/integration' if probe.returncode == 0 else 'main'


def cmd_check(roles: list[str], base: str, head: str) -> int:
    root = repo_root(Path.cwd())
    out = subprocess.run(
        ['git', '-C', str(root), 'diff', '--name-only', f'{base}...{head}'],
        capture_output=True,
        text=True,
        check=True,
    )
    violations = []
    for rel in filter(None, out.stdout.splitlines()):
        verdicts = [may_edit(root, role, rel) for role in roles]
        if not any(ok for ok, _ in verdicts):
            violations.append(f'{rel} (owner: {verdicts[0][1] or "lead"})')
    for v in violations:
        print(v)
    return 1 if violations else 0


def cmd_hook() -> int:
    event = json.load(sys.stdin)
    role = AGENT_ROLES.get(event.get('agent_type', ''))
    if role is None:
        return 0
    tool_input = event.get('tool_input') or {}
    raw = tool_input.get('file_path') or tool_input.get('notebook_path')
    if not raw:
        return 0
    path = Path(raw)
    if not path.is_absolute():
        path = Path(event.get('cwd', '.')) / path
    path = path.resolve()
    root = repo_root(path)
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return 0
    ok, owner = may_edit(root, role, rel)
    if ok:
        return 0
    print(
        f'{rel} is owned by {owner or "the human lead"}, not {role}. '
        'Do not edit it. Ask the owner through SPEC section 7.3 (a message under agent teams, '
        'or a Requests entry in your WP file) and continue with work you own.',
        file=sys.stderr,
    )
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest='mode', required=True)
    who = sub.add_parser('who')
    who.add_argument('paths', nargs='+')
    check = sub.add_parser('check')
    check.add_argument(
        '--role',
        required=True,
        action='append',
        help='repeat for a WP with supporting roles; a file passes if any listed role owns it',
    )
    check.add_argument(
        '--base',
        default=None,
        help='defaults to mig/integration when it exists, else main',
    )
    check.add_argument('--head', default='HEAD')
    sub.add_parser('hook')
    sub.add_parser('base', help='print the default base ref for checks')
    args = parser.parse_args()
    if args.mode == 'who':
        return cmd_who(args.paths)
    if args.mode == 'check':
        return cmd_check(args.role, args.base or default_base(), args.head)
    if args.mode == 'base':
        print(default_base())
        return 0
    return cmd_hook()


if __name__ == '__main__':
    sys.exit(main())
