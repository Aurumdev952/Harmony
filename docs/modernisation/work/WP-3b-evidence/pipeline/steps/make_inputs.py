"""Write harmony_demo feed inputs of N rows built from pipeline/harmony_demo/static_data.

Usage: make_inputs.py <src_root> <out_root> <rows>

Every row names a municipality code from static_data/mapped_locations.csv, so the
fill step's location join matches every row. Values are deterministic in the row
number; no real data.
"""

import csv
import datetime
import gzip
import io
import json
import sys
from pathlib import Path

src, out, rows = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
date = '20261006'
with open(
    src / 'pipeline/harmony_demo/static_data/mapped_locations.csv', newline=''
) as f:
    codes = [r['CleanMunicipalityName'] for r in csv.DictReader(f)]
start = datetime.date(2020, 1, 1)


def day(i: int) -> str:
    return (start + datetime.timedelta(days=i % 730)).isoformat()


yf = out / 'feed/yellow_fever' / date
yf.mkdir(parents=True)
with open(yf / 'yellow_fever_cases.csv', 'w', newline='') as f:
    w = csv.writer(f, delimiter=';', lineterminator='\n')
    w.writerow(['COD_MUN_LPI', 'SEXO', 'IDADE', 'OBITO', 'DT_IS', 'OBSERVACAO'])
    for i in range(rows):
        w.writerow(
            [
                codes[i % len(codes)],
                'MF'[i % 2],
                i % 90,
                ('NAO', 'SIM')[i % 7 == 0],
                day(i // 3),
                '',
            ]
        )

ss = out / 'feed/self_serve' / date
source = 'demo_clinics'
(ss / source).mkdir(parents=True)
(ss / 'active_sources.txt').write_text(source + '\n')
(ss / source / 'config.json').write_text(
    json.dumps(
        {
            'date_column': 'Visit Date',
            'source': source,
            'data_filename': f'{source}.csv.gz',
            'dimensions': [
                {'input_name': 'Municipality', 'output_name': 'MunicipalityName'}
            ],
            'fields': [
                {'input_name': 'Visits', 'output_name': f'{source}_visits'},
                {'input_name': 'Referrals', 'output_name': f'{source}_referrals'},
            ],
        },
        indent=2,
    )
)
with (
    open(ss / source / f'{source}.csv.gz', 'wb') as raw,
    gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as gz,
    io.TextIOWrapper(gz, newline='') as f,
):
    w = csv.writer(f, lineterminator='\n')
    w.writerow(['Municipality', 'Visit Date', 'Visits', 'Referrals'])
    for i in range(rows):
        w.writerow(
            [
                codes[(i * 7) % len(codes)],
                day(i // 5),
                i % 50,
                '' if i % 4 == 0 else i % 3,
            ]
        )
