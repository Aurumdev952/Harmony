'''Differential check: replay every golden case against freshly synthesised Druid
answers (other seeds, and with special values forced on) and write one line per
(case, variant): the sha256 of the response body, or the error.

    uv run --project <tree> python /tmp/core3b/fuzz.py <tree> <out.tsv> [seeds]
'''

import hashlib
import os
import sys
import traceback

root = os.path.abspath(sys.argv[1])
os.chdir(root)
sys.path.insert(0, root)
out_path = sys.argv[2]
seeds = int(sys.argv[3]) if len(sys.argv) > 3 else 5

from tests.golden.harness import bootstrap  # noqa: E402

bootstrap()

from tests.golden.harness import load_cases, run_case, to_json_text  # noqa: E402
from tests.golden.synth import synthesize  # noqa: E402

bodies_dir = out_path + '.bodies'
os.makedirs(bodies_dir, exist_ok=True)
lines = []
for case in load_cases():
    base_options = dict(case.meta.get('druid', {}))
    variants = [(f'seed{s}', base_options) for s in range(seeds)]
    if not base_options.get('empty'):
        variants += [
            (f'special{s}', {**base_options, 'special_values': True})
            for s in range(seeds)
        ]
    for label, options in variants:
        name = f'{case.name}#{label}'
        try:
            _, body = run_case(case, lambda q, n=name, o=options: synthesize(n, q, o))
            text = to_json_text(body)
            with open(
                os.path.join(bodies_dir, name + '.json'), 'w', encoding='utf-8'
            ) as f:
                f.write(text)
            result = hashlib.sha256(text.encode()).hexdigest()
        except Exception as error:  # noqa: BLE001
            result = 'ERROR ' + repr(error).splitlines()[0][:200]
            traceback.print_exc(limit=1)
        lines.append(f'{name}\t{result}')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
print(len(lines), 'variants')
