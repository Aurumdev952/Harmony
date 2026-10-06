"""Pipeline steps run on the one CPython interpreter (WP-3b): no PyPy switch is left.

The harmony_demo process steps used to call ``SetupEnvForPyPy``, which switched to a
``venv_pypy3`` venv, and two modules carried PyPy-only fast paths. These tests fail if
any of that comes back, and run the three per-row steps the way Zeus chains them.
"""

import csv
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PIPELINE_CODE = ('pipeline', 'data/pipeline', 'util/pipeline')
PYPY = re.compile(rb'(?i)pypy')
STEPS = REPO / 'pipeline/harmony_demo/process/run'
DATE = '20261006'


def test_pipeline_code_has_no_pypy_switch_or_branch():
    hits = [
        f'{path.relative_to(REPO)}:{number}'
        for top in PIPELINE_CODE
        for path in sorted((REPO / top).rglob('*'))
        if path.is_file() and '__pycache__' not in path.parts
        for number, line in enumerate(path.read_bytes().splitlines(), 1)
        if PYPY.search(line)
    ]
    assert hits == []


def _stage_feeds(out: Path) -> None:
    yellow_fever = out / 'feed/yellow_fever' / DATE
    yellow_fever.mkdir(parents=True)
    fixture = REPO / 'tests/pipeline/fixtures/process_csv/yellow_fever/input.csv'
    shutil.copyfile(fixture, yellow_fever / 'yellow_fever_cases.csv')

    self_serve = out / 'feed/self_serve' / DATE
    (self_serve / 'clinics').mkdir(parents=True)
    (self_serve / 'active_sources.txt').write_text('clinics\n')
    config = {
        'date_column': 'Date',
        'source': 'clinics',
        'data_filename': 'clinics.csv.gz',
        'dimensions': [{'input_name': 'Code', 'output_name': 'MunicipalityName'}],
        'fields': [{'input_name': 'Visits', 'output_name': 'clinics_visits'}],
    }
    (self_serve / 'clinics/config.json').write_text(json.dumps(config))
    with open(fixture, newline='') as f:
        codes = sorted({row['COD_MUN_LPI'] for row in csv.DictReader(f, delimiter=';')})
    data = 'Code,Date,Visits\n' + ''.join(f'{c},2020-01-15,3\n' for c in codes)
    (self_serve / 'clinics/clinics.csv.gz').write_bytes(gzip.compress(data.encode()))


def _run_step(script: Path, source: str, env: dict[str, str], out: Path) -> str:
    step_env = {
        **env,
        'PIPELINE_FEED_DIR': str(out / 'feed' / source / DATE),
        'PIPELINE_TMP_DIR': str(out / 'tmp' / source / DATE),
    }
    Path(step_env['PIPELINE_TMP_DIR']).mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ['bash', str(script)], env=step_env, capture_output=True, text=True, timeout=300
    )
    log = result.stdout + result.stderr
    assert result.returncode == 0, log
    return log


def test_demo_process_steps_run_on_the_active_interpreter(tmp_path):
    for binary in ('lz4', 'gzip'):
        assert shutil.which(binary), f'{binary} is required'
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    if shutil.which('pigz') is None:
        (bin_dir / 'pigz').symlink_to(shutil.which('gzip'))
    out = tmp_path / 'out_root'
    _stage_feeds(out)
    for source in ('self_serve', 'yellow_fever'):
        (out / 'out' / source / DATE).mkdir(parents=True)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith('PYTHON') and key != 'ZEN_ENV'
    }
    env.update(
        {
            # `python` in the steps' shebangs resolves to this interpreter's venv.
            'PATH': os.pathsep.join(
                (str(Path(sys.executable).parent), str(bin_dir), os.environ['PATH'])
            ),
            'PYTHONPATH': str(REPO),
            'ZEN_ENV': 'harmony_demo',
            'PIPELINE_SRC_ROOT': str(REPO),
            'PIPELINE_UTILS_DIR': str(REPO / 'util/pipeline'),
            'PIPELINE_BIN_DIR': str(REPO / 'pipeline/harmony_demo/process'),
            'PIPELINE_OUT_ROOT': str(out),
            'PIPELINE_DATE': DATE,
        }
    )

    logs = [
        _run_step(STEPS / '00_self_serve/10_process', 'self_serve', env, out),
        _run_step(STEPS / '00_yellow_fever/10_process', 'yellow_fever', env, out),
        _run_step(
            STEPS / '90_shared/10_fill_dimension_data.abort_fail', 'shared', env, out
        ),
    ]

    assert [log for log in logs if 'pypy' in log.lower()] == []
    for source in ('self_serve', 'yellow_fever'):
        shard = out / 'out' / source / DATE / 'processed_rows.0.json.gz'
        assert gzip.decompress(shard.read_bytes()).count(b'\n') > 0, source
