"""In-process access to the per-row pipeline code, for property and pinning tests.

This imports ``config`` for harmony_demo and internals that WP-8d removes
(``_get_date``, ``Aggregator``, ``BaseRow.to_druid_json_iterator``). WP-8d rewrites
these helpers against its Polars code; the golden cases do not depend on them.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

from pipeline_fixtures import REPO_ROOT

if os.environ.setdefault('ZEN_ENV', 'harmony_demo') != 'harmony_demo':
    raise RuntimeError('tests/pipeline imports config for ZEN_ENV=harmony_demo only')
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.datatypes import BaseRowType, DimensionFactoryType  # noqa: E402, I001
from data.pipeline.scripts.process_csv import Aggregator, _get_date  # noqa: E402

__all__ = [
    'BaseRowType',
    'get_date',
    'metadata_collector',
    'run_aggregator',
    'write_csv',
]

get_date = _get_date

MAPPING_HEADER = [
    'CleanStateName',
    'CleanMunicipalityName',
    'CanonicalStateName',
    'CanonicalMunicipalityName',
]


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with open(path, 'w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def metadata_collector(
    mapping: dict[tuple[str, str], tuple[str, str]],
    metadata: dict[tuple[str, str], dict[str, str]],
    metadata_columns: tuple[str, ...],
    directory: Path,
):
    """Build fill_dimension_data's join from in-memory mapping and metadata tables."""
    mapping_path = directory / 'mapped_locations.csv'
    metadata_path = directory / 'metadata_mapped.csv'
    write_csv(
        mapping_path,
        MAPPING_HEADER,
        [[*clean, *canonical] for clean, canonical in mapping.items()],
    )
    write_csv(
        metadata_path,
        ['StateName', 'MunicipalityName', *metadata_columns],
        [
            [*key, *(values[c] for c in metadata_columns)]
            for key, values in metadata.items()
        ],
    )
    return DimensionFactoryType.create_metadata_collector(
        str(metadata_path), str(mapping_path)
    )


def run_aggregator(
    header: list[str], rows: list[list[str]], directory: Path, dimensions: list[str]
) -> tuple[list[dict], list[str], list[dict]]:
    """Run process_csv's Aggregator on a CSV; return base rows, fields, locations."""
    input_path = directory / 'input.csv'
    write_csv(input_path, header, rows)
    aggregator = Aggregator(
        datecol='Date',
        source='demo',
        output_field_prefix='demo',
        dimensions=dimensions,
    )
    aggregator.process(
        str(input_path),
        str(directory / 'rows.json.lz4'),
        str(directory / 'locations.csv'),
        str(directory / 'fields.csv'),
        None,
    )
    out = subprocess.run(
        ['lz4cat', str(directory / 'rows.json.lz4')],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    with open(directory / 'locations.csv', newline='') as handle:
        locations = list(csv.DictReader(handle))
    fields = (directory / 'fields.csv').read_text().split()
    return [json.loads(line) for line in out.splitlines()], fields, locations
