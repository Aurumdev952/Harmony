"""The lead may edit paths no ownership row covers; the gate counts lead instances."""

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / 'scripts' / 'agents' / f'{name}.py'
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_lead_may_edit_unowned_paths_only():
    ownership = _load('ownership')
    unowned = 'scripts/create_bot_accounts.sh'
    assert ownership.owner_of(ROOT, unowned) is None
    assert ownership.may_edit(ROOT, 'lead', unowned) == (True, 'lead')
    assert ownership.may_edit(ROOT, 'qa', unowned)[0] is False
    owned = ownership.owner_of(ROOT, 'web/server/routes/api.py')
    assert owned is not None
    assert ownership.may_edit(ROOT, 'lead', 'web/server/routes/api.py')[0] is False


def test_gate_counts_lead_instances_and_log_lines():
    gate = _load('task_gate')
    text = 'instances:\n  - name: lead-1\n    files: [data/pydruid_query/**]\n---\n- 2026-10-05 lead-1 deleted the module\n'
    assert 'lead' in gate.contributing_roles(text)
