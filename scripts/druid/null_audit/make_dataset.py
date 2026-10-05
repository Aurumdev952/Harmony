'''Write the deterministic synthetic rows the null audit indexes.

The rows follow what the pipeline writes (tests/pipeline goldens): one row per
(dimensions, date, source, field) with a numeric `val`; location dimensions that
a row lacks are written as `''` (state-level reports have `''` municipality
columns); a categorical column the source did not map is absent, so it is a true
null; zero values fold into one row whose `field` is multi-valued and `val` is 0.

The locations are the golden suite's sample, so golden filters and policies
select real rows. Rows are sparse, so filtered aggregators are empty in some
groups. A few rows carry each null shape (absent Sex or Age, a location that did
not match), so every null path the query builder meets is present in the data.
'''

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterator, List, Union

from tests.golden.synth import LOCATION_DIMENSIONS, LOCATIONS

SEED = 20261004
FIELD = 'yellow_fever_cases'
SOURCES = ('yellow_fever', 'yellow_fever_lab')
SEXES = ('F', 'M')
AGES = ('15-49', '50+')
DEATHS = ('0', '1')
PRESENCE = 0.35
NULL_SHAPE_RATE = 0.05

Row = Dict[str, Union[str, int, List[str]]]


def _dates() -> Iterator[date]:
    day = date(2018, 1, 1)
    while day < date(2021, 1, 1):
        yield day
        day = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    day = date(2021, 1, 4)
    while day < date(2026, 1, 1):
        if not date(2024, 1, 1) <= day < date(2024, 5, 1):
            yield day
        day += timedelta(days=7)
    day = date(2024, 1, 1)
    while day < date(2024, 5, 1):
        yield day
        day += timedelta(days=1)


def _location(values: tuple) -> Row:
    return {name: value or '' for name, value in zip(LOCATION_DIMENSIONS, values)}


def rows(seed: int = SEED) -> List[Row]:
    rng = random.Random(seed)  # noqa: S311 seeded, so the dataset is reproducible
    unmatched = {name: '' for name in LOCATION_DIMENSIONS}
    output: List[Row] = []
    for day in sorted(set(_dates())):
        for source in SOURCES:
            if source != SOURCES[0] and rng.random() > 0.2:
                continue
            for values in LOCATIONS:
                for sex in SEXES:
                    for age in AGES:
                        for death in DEATHS:
                            if rng.random() > PRESENCE:
                                continue
                            row: Row = {
                                **_location(values),
                                'date': day.isoformat(),
                                'Real_Date': day.isoformat(),
                                'source': source,
                                'Sex': sex,
                                'Age': age,
                                'Death': death,
                                'field': FIELD,
                                'val': rng.choice((0, 0, 1, 2, 3, 5, 8, 13, 21)),
                            }
                            shape = rng.random()
                            if shape < NULL_SHAPE_RATE:
                                del row['Sex']
                            elif shape < 2 * NULL_SHAPE_RATE:
                                del row['Age']
                            elif shape < 2.4 * NULL_SHAPE_RATE:
                                row.update(unmatched)
                            if row['val'] == 0:
                                row['field'] = [FIELD]
                            output.append(row)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('out_dir', type=Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    data = rows()
    with open(args.out_dir / 'rows.json', 'w', encoding='utf-8') as handle:
        for row in data:
            handle.write(json.dumps(row, sort_keys=True) + '\n')
    print(f'{len(data)} rows written to {args.out_dir / "rows.json"}')


if __name__ == '__main__':
    main()
