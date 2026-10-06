"""summarise.py <driver output>: per row count and step, the median and range of wall
time and the peak RSS (largest process / all processes of the step) for each image,
and whether every run's outputs are identical."""

import re
import statistics
import sys
from collections import defaultdict

wall = defaultdict(list)
rss = defaultdict(list)
total = defaultdict(list)
digests = defaultdict(set)
pythons = {}
key = None
for line in open(sys.argv[1]):
    run = re.match(r'rows=(\d+) image=(\w+) run=\d+ ', line)
    if run:
        rows, image = int(run[1]), run[2]
        pythons[image] = re.search(r'step_python=(\S+)', line)[1].replace('_', ' ')
        for name, code, secs, mib, tot in re.findall(
            r'step=(\w+) exit=(\d+) wall_s=([\d.]+) peak_rss_mib=(\d+) peak_total_mib=(\d+)',
            line,
        ):
            if code != '0':
                sys.exit(f'step failed: {line}')
            wall[rows, name, image].append(float(secs))
            rss[rows, name, image].append(int(mib))
            total[rows, name, image].append(int(tot))
        key = rows
    elif line.startswith('  outputs ') and key is not None:
        digests[key].add(line.split(None, 1)[1].strip())


def cell(rows, name, image):
    w = wall[rows, name, image]
    return (
        f'{statistics.median(w):.2f} s ({min(w):.2f}-{max(w):.2f}), '
        f'{max(rss[rows, name, image])} / {max(total[rows, name, image])} MiB'
    )


print(
    f'| Rows | Step | {pythons["base"]} (base) | {pythons["branch"]} (branch) | Median ratio |'
)
print('|---|---|---|---|---|')
for rows in sorted(digests):
    for name in ('process_csv', 'self_serve', 'fill_dimension_data'):
        ratio = statistics.median(wall[rows, name, 'branch']) / statistics.median(
            wall[rows, name, 'base']
        )
        print(
            f'| {rows:,} | {name} | {cell(rows, name, "base")} '
            f'| {cell(rows, name, "branch")} | {ratio:.1f} |'
        )
for rows in sorted(digests):
    runs = len(wall[rows, 'process_csv', 'base']) + len(
        wall[rows, 'process_csv', 'branch']
    )
    same = 'identical' if len(digests[rows]) == 1 else 'DIFFERENT'
    print(f'{rows:,} rows: outputs of all {runs} runs {same}')
