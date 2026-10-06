'''Write /tmp/core3b/body_200mb.json.gz: about 200 MB of Druid array rows.'''

import gzip
import random

STATES = ['Acre', 'Pará', 'Roraima', 'São Paulo', 'Maranhão', 'Ceará', 'Piauí']
MUNIS = [f'Município {i} — Zona {i % 7}' for i in range(3000)]
rng = random.Random(3)  # noqa: S311 (reproducible benchmark data)
target = 200 * 1000 * 1000
size = 0
with gzip.open('/tmp/core3b/body_200mb.json.gz', 'wb', compresslevel=6) as f:  # noqa: S108 (scratch data)
    f.write(b'[')
    first = True
    while size < target:
        vals = []
        for _ in range(6):
            r = rng.random()
            vals.append(
                'null'
                if r < 0.15
                else ('"NaN"' if r < 0.16 else repr(rng.uniform(-1e6, 1e9)))
            )
        row = (
            f'[{1514764800000 + rng.randrange(96) * 2678400000}, "{rng.choice(STATES)}", '
            f'"{rng.choice(MUNIS)}", "{rng.choice("MF")}", {", ".join(vals)}, '
            f'{rng.randint(0, 5000)}, {rng.randint(0, 5000)}, -9223372036854775808]'
        ).encode()
        if not first:
            f.write(b',')
        f.write(row)
        size += len(row) + 1
        first = False
    f.write(b']')
print('uncompressed bytes', size + 1)
