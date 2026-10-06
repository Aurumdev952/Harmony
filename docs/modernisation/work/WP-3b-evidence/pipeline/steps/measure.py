"""measure.py <name> <script> <log>: run one Zeus step with bash and print its exit
code, wall time and memory.

Memory is sampled from /proc every 20 ms over every process in the container except
PID 1 (the runner) and this one, which leaves the step and its descendants.
peak_rss_mib is the largest single process (its VmHWM, high-water mark);
peak_total_mib is the largest sampled sum of VmRSS. ru_children_mib is
RUSAGE_CHILDREN's ru_maxrss, for comparison: it counts only descendants whose
usage reached this process through wait().
"""

import os
import resource
import subprocess
import sys
import threading
import time

name, script, log = sys.argv[1], sys.argv[2], sys.argv[3]
skip = {'1', str(os.getpid())}
peak_one = peak_total = 0
done = threading.Event()


def kib(status: str, field: str) -> int:
    for line in status.splitlines():
        if line.startswith(field):
            return int(line.split()[1])
    return 0


def sample() -> None:
    global peak_one, peak_total
    while not done.is_set():
        total = 0
        for pid in os.listdir('/proc'):
            if not pid.isdigit() or pid in skip:
                continue
            try:
                with open(f'/proc/{pid}/status') as f:
                    status = f.read()
            except OSError:
                continue
            total += kib(status, 'VmRSS:')
            peak_one = max(peak_one, kib(status, 'VmHWM:'))
        peak_total = max(peak_total, total)
        time.sleep(0.02)


sampler = threading.Thread(target=sample)
sampler.start()
start = time.perf_counter()
with open(log, 'w') as f:
    code = subprocess.run(
        ['bash', script], stdout=f, stderr=subprocess.STDOUT
    ).returncode
wall = time.perf_counter() - start
done.set()
sampler.join()
print(
    f'step={name} exit={code} wall_s={wall:.2f} '
    f'peak_rss_mib={peak_one / 1024:.0f} peak_total_mib={peak_total / 1024:.0f} '
    f'ru_children_mib={resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024:.0f}'
)
sys.exit(code)
