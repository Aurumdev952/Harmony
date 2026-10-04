"""Run the harmony_demo per-row pipeline steps on fixtures and canonicalise their outputs.

Two layers of golden output are kept per case:

- ``raw/``: every file the steps wrote, decompressed, byte for byte. This pins today's
  serialisation (key order, CRLF line endings, shard boundaries, zero-field collapse).
- ``canonical/``: the same data with ordering and container format removed. This is
  the layer a reimplementation (WP-8d, Polars and Parquet) must reproduce. The
  ``canonical_*`` functions take plain rows so a Parquet reader can feed them.
"""

from __future__ import annotations

import csv
import dataclasses
import gzip
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

SUITE_DIR = Path(__file__).resolve().parent
REPO_ROOT = SUITE_DIR.parents[1]
FIXTURES_DIR = SUITE_DIR / 'fixtures'
GOLDEN_DIR = SUITE_DIR / 'golden'
DEMO_STATIC_DIR = REPO_ROOT / 'pipeline' / 'harmony_demo' / 'static_data'
PROCESS_CSV = REPO_ROOT / 'data' / 'pipeline' / 'scripts' / 'process_csv.py'
FILL_DIMENSION_DATA = REPO_ROOT / 'data' / 'pipeline' / 'scripts' / 'fill_dimension_data.py'
PROCESS_CSV_WRAPPER = (
    REPO_ROOT / 'data' / 'pipeline' / 'self_serve' / 'scripts' / 'process_csv_wrapper.py'
)

DRUID_ROWS_PATTERN = re.compile(r'^processed_rows\.\d+\.json$')
BASE_ROWS_PATTERN = re.compile(r'^processed_data.*\.json$')
VALUE_COLUMN = 'val'
FIELD_COLUMN = 'field'
# fill_dimension_data --use_experimental_parser writes non-zero values as one
# {"data": {field: val}} row for Druid's nestedJson parser.
NESTED_DATA_COLUMN = 'data'


@dataclasses.dataclass(frozen=True)
class Step:
    script: Path
    args: tuple[str, ...]
    expect_returncode: int = 0


@dataclasses.dataclass(frozen=True)
class Case:
    """One fixture run. ``inputs`` maps a path under the work dir to a fixture path.

    A destination ending in ``.gz`` or ``.lz4`` is compressed from the plain fixture,
    so every input format reads the same committed text.
    """

    name: str
    steps: tuple[Step, ...]
    inputs: dict[str, str] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        assert all(step.expect_returncode == 0 for step in self.steps[:-1]), (
            f'{self.name}: only the last step may be expected to fail'
        )

    @property
    def aborts(self) -> bool:
        """An aborting case pins only the error: partial outputs depend on pipe buffering."""
        return self.steps[-1].expect_returncode != 0


def require_binaries() -> None:
    missing = [tool for tool in ('lz4', 'lz4cat', 'gzip') if shutil.which(tool) is None]
    if missing:
        raise RuntimeError(
            f'The pipeline steps shell out to {missing}; install them (apt: lz4 gzip).'
        )


def tool_dir(base: Path) -> Path:
    """Return a directory to prepend to PATH so that ``pigz`` resolves.

    The steps call ``pigz``; when it is absent, gzip is a drop-in for the flags they use
    (``-d -c``, ``-<level>``) and produces the same decompressed bytes.
    """
    bin_dir = base / 'bin'
    bin_dir.mkdir(parents=True, exist_ok=True)
    if shutil.which('pigz') is None and not (bin_dir / 'pigz').exists():
        (bin_dir / 'pigz').symlink_to(shutil.which('gzip'))
    return bin_dir


def step_env(bin_dir: Path, hash_seed: str | None = None) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith('PYTHON') and key not in ('ZEN_ENV', 'LC_ALL', 'LANG')
    }
    env.update(
        {
            'ZEN_ENV': 'harmony_demo',
            'PYTHONPATH': str(REPO_ROOT),
            'PYTHONUTF8': '1',
            'LC_ALL': 'C.UTF-8',
            'TZ': 'UTC',
            'PATH': f'{bin_dir}{os.pathsep}{os.environ.get("PATH", "")}',
        }
    )
    if hash_seed is not None:
        env['PYTHONHASHSEED'] = hash_seed
    return env


def _expand(arg: str, work: Path, out: Path) -> str:
    return (
        arg.replace('{work}', str(work))
        .replace('{out}', str(out))
        .replace('{static}', str(DEMO_STATIC_DIR))
    )


def _stage_inputs(case: Case, work: Path) -> None:
    for dest_name, fixture_rel in case.inputs.items():
        source = FIXTURES_DIR / fixture_rel
        dest = work / dest_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest_name.endswith('.gz'):
            dest.write_bytes(gzip.compress(source.read_bytes(), mtime=0))
        elif dest_name.endswith('.lz4'):
            subprocess.run(['lz4', '-q', '-f', str(source), str(dest)], check=True)
        else:
            shutil.copyfile(source, dest)


def _failure_text(stderr: str) -> str:
    """Keep the final exception and its message; drop tracebacks and log timestamps."""
    lines = stderr.rstrip('\n').split('\n')
    last_traceback = max(
        (idx for idx, line in enumerate(lines) if line.startswith('Traceback ')), default=0
    )
    for idx in range(last_traceback, len(lines)):
        if re.match(r'^[A-Za-z_.]+(Error|Exception): ', lines[idx]):
            return '\n'.join(lines[idx:]) + '\n'
    return lines[-1] + '\n'


def run_case(case: Case, base: Path, hash_seed: str | None = None) -> Path:
    """Run every step of ``case`` under ``base`` and return the output directory."""
    if sys.flags.optimize:
        raise RuntimeError('The steps rely on assert; never run them with -O.')
    require_binaries()
    work = base / 'work'
    out = base / 'out'
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    _stage_inputs(case, work)
    env = step_env(tool_dir(base), hash_seed)
    for index, step in enumerate(case.steps):
        command = [sys.executable, str(step.script)]
        command.extend(_expand(arg, work, out) for arg in step.args)
        result = subprocess.run(
            command, cwd=work, env=env, capture_output=True, text=True, timeout=300
        )
        if result.returncode != step.expect_returncode:
            raise AssertionError(
                f'{case.name} step {index} ({step.script.name}) exited '
                f'{result.returncode}, expected {step.expect_returncode}.\n'
                f'stderr:\n{result.stderr}'
            )
        if step.expect_returncode != 0:
            for path in out.iterdir():
                path.unlink()
            (out / f'step{index}.{step.script.stem}.error.txt').write_text(
                _failure_text(result.stderr)
            )
    return out


def _decompress(path: Path) -> tuple[str, bytes]:
    if path.name.endswith('.lz4'):
        data = subprocess.run(['lz4cat', str(path)], check=True, capture_output=True).stdout
        return path.name[: -len('.lz4')], data
    if path.name.endswith('.gz'):
        return path.name[: -len('.gz')], gzip.decompress(path.read_bytes())
    return path.name, path.read_bytes()


def capture_raw(out: Path) -> dict[str, bytes]:
    """Every output file, decompressed, keyed by its name without compression suffix."""
    captured = {}
    for path in sorted(out.iterdir()):
        name, data = _decompress(path)
        assert name not in captured, f'two outputs decompress to {name}'
        captured[name] = data
    return captured


def _json_lines(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.decode('utf-8').splitlines() if line]


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def canonical_rows(rows: Iterable[dict]) -> str:
    """Rows as sorted JSON lines with sorted keys. JSON keeps 1 and 1.0 apart."""
    return ''.join(f'{line}\n' for line in sorted(_dump(row) for row in rows))


def _json_type(value: object) -> str:
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, float):
        return 'float'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        inner = sorted({_json_type(item) for item in value})
        return f'array<{"|".join(inner)}>'
    if value is None:
        return 'null'
    return type(value).__name__


def canonical_schema(rows: Sequence[dict]) -> str:
    """Column set, the JSON types seen per column, and how many rows carry each column.

    Rows matched to a canonical location without metadata omit the ID and lat/lon
    columns, so presence is part of the schema.
    """
    types: dict[str, set] = {}
    present: dict[str, int] = {}
    for row in rows:
        for key, value in row.items():
            types.setdefault(key, set()).add(_json_type(value))
            present[key] = present.get(key, 0) + 1
    schema = {
        'row_count': len(rows),
        'columns': {
            key: {'types': sorted(types[key]), 'rows_present': present[key]}
            for key in sorted(types)
        },
    }
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + '\n'


def _druid_facts(row: dict) -> list[tuple[str, float]]:
    """(field, val) pairs of one Druid row, in the flat or the nestedJson row shape."""
    if NESTED_DATA_COLUMN in row:
        return list(row[NESTED_DATA_COLUMN].items())
    fields = row[FIELD_COLUMN]
    return [
        (field, row[VALUE_COLUMN]) for field in (fields if isinstance(fields, list) else [fields])
    ]


def canonical_rollup(rows: Iterable[dict]) -> str:
    """What Druid stores per query-visible key after ingest rollup.

    Mirrors ``db/druid/indexing``: queryGranularity none, metrics count, doubleSum,
    doubleMin and doubleMax over ``val``. A multi-valued ``field`` is exploded, because
    a filter on one field id matches the collapsed zero row. The sum is ``math.fsum``,
    the correctly rounded sum, so it does not depend on row order.
    """
    groups: dict[str, list[float]] = {}
    for row in rows:
        for field, value in _druid_facts(row):
            key = {k: v for k, v in row.items() if k not in (VALUE_COLUMN, NESTED_DATA_COLUMN)}
            key[FIELD_COLUMN] = field
            groups.setdefault(_dump(key), []).append(float(value))
    lines = []
    for key, values in groups.items():
        lines.append(
            _dump(
                {
                    'dimensions': json.loads(key),
                    'count': len(values),
                    'sum': math.fsum(values),
                    'min': min(values),
                    'max': max(values),
                }
            )
        )
    return ''.join(f'{line}\n' for line in sorted(lines))


def _canonical_csv(data: bytes) -> str:
    return canonical_rows(csv.DictReader(io.StringIO(data.decode('utf-8'), newline='')))


def _canonical_lines(data: bytes) -> str:
    return ''.join(f'{line}\n' for line in sorted(data.decode('utf-8').splitlines()))


def canonicalise(raw: dict[str, bytes]) -> dict[str, str]:
    canonical: dict[str, str] = {}
    druid_rows: list[dict] = []
    has_druid_shards = False
    for name, data in raw.items():
        if DRUID_ROWS_PATTERN.match(name):
            has_druid_shards = True
            druid_rows.extend(_json_lines(data))
        elif BASE_ROWS_PATTERN.match(name):
            canonical[f'{name[: -len(".json")]}.base_rows.jsonl'] = canonical_rows(
                _json_lines(data)
            )
        elif name.startswith('fields') and name.endswith('.csv'):
            canonical[f'{name}.lines.txt'] = _canonical_lines(data)
        elif name.endswith('.csv'):
            canonical[f'{name}.jsonl'] = _canonical_csv(data)
        elif name.endswith('.json'):
            canonical[name] = (
                json.dumps(json.loads(data), indent=2, sort_keys=True, ensure_ascii=False) + '\n'
            )
    if has_druid_shards:
        canonical['druid_rows.jsonl'] = canonical_rows(druid_rows)
        canonical['druid_schema.json'] = canonical_schema(druid_rows)
        canonical['druid_rollup.jsonl'] = canonical_rollup(druid_rows)
    return canonical


def golden_files(case_name: str, layer: str) -> dict[str, bytes]:
    directory = GOLDEN_DIR / case_name / layer
    if not directory.is_dir():
        return {}
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


def write_golden(case_name: str, raw: dict[str, bytes], canonical: dict[str, str]) -> None:
    case_dir = GOLDEN_DIR / case_name
    if case_dir.exists():
        shutil.rmtree(case_dir)
    for layer, files in (
        ('raw', raw),
        ('canonical', {k: v.encode('utf-8') for k, v in canonical.items()}),
    ):
        if not files:
            continue
        layer_dir = case_dir / layer
        layer_dir.mkdir(parents=True)
        for name, data in files.items():
            (layer_dir / name).write_bytes(data)
