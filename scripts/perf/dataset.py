"""Write the synthetic yellow-fever case file the performance baseline indexes.

The real source (the Brazilian ministry's open line list, fetched by
pipeline/harmony_demo/process/run/00_yellow_fever/00_fetch) has about 2,800 rows,
too few for latency to mean anything, and it is patient-level. This file has the
same columns and value vocabulary, at a realistic size, and no real person in it:

- municipalities are the public IBGE codes the demo already maps
  (pipeline/harmony_demo/static_data/mapped_locations.csv), weighted by a Zipf law
  over a seeded ranking, so a few municipalities carry most cases;
- dates follow the southern-summer season of yellow fever (December to April);
- sex, age and outcome are drawn independently.

The output depends only on --rows, --seed and the dates, so a later agent on any
machine regenerates the same bytes (check the sha256 recorded in WP-1a).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAPPED_LOCATIONS = REPO_ROOT / 'pipeline/harmony_demo/static_data/mapped_locations.csv'

COLUMNS = ('COD_MUN_LPI', 'SEXO', 'IDADE', 'OBITO', 'DT_IS')

# Relative case weight per calendar month, January first.
MONTH_WEIGHTS = (1.0, 1.0, 0.8, 0.5, 0.25, 0.1, 0.05, 0.05, 0.05, 0.1, 0.3, 0.7)
OUTCOMES = (('NAO', 0.62), ('SIM', 0.33), ('IGN', 0.05))
SEXES = (('M', 0.8), ('F', 0.2))


def municipality_codes() -> list[str]:
    with MAPPED_LOCATIONS.open(encoding='utf-8', newline='') as handle:
        return sorted(
            {
                row['CleanMunicipalityName']
                for row in csv.DictReader(handle)
                if row['CleanMunicipalityName'] and row['CanonicalMunicipalityName']
            }
        )


def day_weights(start: dt.date, end: dt.date) -> tuple[list[dt.date], list[float]]:
    days = [start + dt.timedelta(n) for n in range((end - start).days + 1)]
    return days, [MONTH_WEIGHTS[day.month - 1] for day in days]


def rows(count: int, seed: int, start: dt.date, end: dt.date):
    rng = random.Random(seed)
    codes = municipality_codes()
    rng.shuffle(codes)
    code_weights = [1.0 / rank for rank in range(1, len(codes) + 1)]
    days, weights = day_weights(start, end)
    outcome_values, outcome_weights = zip(*OUTCOMES)
    sex_values, sex_weights = zip(*SEXES)
    for _ in range(count):
        yield (
            rng.choices(codes, code_weights)[0],
            rng.choices(sex_values, sex_weights)[0],
            str(min(95, int(rng.gammavariate(4.0, 9.0)))),
            rng.choices(outcome_values, outcome_weights)[0],
            rng.choices(days, weights)[0].isoformat(),
        )


def write(path: Path, count: int, seed: int, start: dt.date, end: dt.date) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle, delimiter=';', lineterminator='\n')
        writer.writerow(COLUMNS)
        writer.writerows(rows(count, seed, start, end))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('output', type=Path)
    parser.add_argument('--rows', type=int, default=200_000)
    parser.add_argument('--seed', type=int, default=20261004)
    parser.add_argument(
        '--start', type=dt.date.fromisoformat, default=dt.date(2023, 1, 1)
    )
    parser.add_argument(
        '--end', type=dt.date.fromisoformat, default=dt.date(2025, 12, 31)
    )
    args = parser.parse_args()
    digest = write(args.output, args.rows, args.seed, args.start, args.end)
    print(f'{args.output}: {args.rows} rows, sha256 {digest}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
