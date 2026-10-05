"""Applies one mutation at a time to db/postgres/utils.py, runs tests/db, restores."""

import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[4]
TARGET = ROOT / "db/postgres/utils.py"
ORIGINAL = TARGET.read_text()

MUTATIONS = {
    "no count check": (
        "            for table in staged:\n                table.check_matches_staging(cursor)\n",
        "",
    ),
    "delete absent rows before upsert": (
        "            for table in referenced:\n                LOG.info('Importing table: %s', table.name)\n                table.insert(cursor)\n            for table in reversed(referenced):\n                table.delete_rows_not_staged(cursor)\n",
        "            for table in reversed(referenced):\n                table.delete_rows_not_staged(cursor)\n            for table in referenced:\n                LOG.info('Importing table: %s', table.name)\n                table.insert(cursor)\n",
    ),
    "sequence may move back": (
        "'(SELECT CASE WHEN is_called THEN last_value ELSE last_value - 1 END'\n                ' FROM {sequence}),'",
        "'(SELECT 0 FROM {sequence}),'",
    ),
    "leaves upserted, not emptied": (
        "            for table in leaves:\n                table.empty(cursor)\n",
        "",
    ),
}

try:
    for label, (old, new) in MUTATIONS.items():
        assert ORIGINAL.count(old) == 1, label
        TARGET.write_text(ORIGINAL.replace(old, new))
        result = subprocess.run(
            ["uv", "run", "pytest", "tests/db", "-q", "-p", "no:warnings"],
            cwd=ROOT,
            env={**os.environ, "ZEN_ENV": "harmony_demo"},
            capture_output=True,
            text=True,
            check=False,
        )
        lines = result.stdout.splitlines()
        failed = [line for line in lines if line.startswith("FAILED")]
        print(f"{label}: {lines[-1] if lines else result.stderr[-300:]}")
        for line in failed:
            print("   ", line.split("::")[-1].split(" ")[0])
finally:
    TARGET.write_text(ORIGINAL)
