# Paired performance run 2026-10-05-2ddc30cdb0-vs-b8b80deeb5-r2-merge-smoke

- Code: reference `2ddc30cdb038a9f5be71aaae3ad1df8ba770f190`, candidate `b8b80deeb5207395662fe5d54f54d84bc3eae3f1` (dirty), run 2026-10-05T22:30:53+00:00
- Host: Intel(R) Core(TM) Ultra 9 285H, 16 logical CPUs, 62.2 GiB, Linux 7.0.0-38-generic, load [15.75, 18.75, 18.74] at start, [13.39, 17.06, 18.13] at end; Docker 29.8.2
- Druid 0.23.0, datasource harmony_demo_20261004
- Method: 30 timed rounds after 3 warm-up, concurrency 1, intervals widened to 2023-01-01/2026-01-01, caches warm (Druid broker and historical caches on, as druid_setup ships them)
- Narrower intervals: table_disaggregated 2025-12-01/2026-01-01
- Dashboards (endpoint `dashboard`, time to last tile): 30 loads after 2 warm-up, ?screenshot=1 at 1440x900, fresh browser context per load, requests leaving the stack aborted; ends at the first frame with every query tile rendered; bytes are the median of headers plus encoded bodies received before the last tile
- Pairing: reference and candidate apps on one host against one Druid; each round sends the case to both, reference first in even rounds and candidate first in odd ones; a case regresses when its p95 ratio or its paired median ratio (median over rounds of candidate over reference time) is above 1.10 with a paired-bootstrap lower bound above 1; every request on a new connection
- Dataset: harmony_demo_20261004 (scripts/perf/dataset.py seed 20261004)

## Verdict

Candidate over reference; a case regresses when its p95 ratio or its paired median ratio is over 1.10 and that ratio's lower bound (one-sided 1.25%, paired bootstrap of 4000 resamples) is over 1. `detects` is the smallest slowdown of every candidate request that would have failed the case.

| case | reference p95 ms | candidate p95 ms | p95 ratio | lower bound | paired median ratio | lower bound | detects | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| bar_graph_sum_by_state_month | 243.2 | 253.7 | 1.043 | 0.269 | 1.072 | 0.787 | 1.271 | ok |
| line_graph_time_by_state | 157.1 | 156.8 | 0.998 | 0.898 | 1.042 | 0.910 | 1.099 | ok |
| dq_data_quality_table | 237.9 | 195.6 | 0.822 | 0.360 | 0.999 | 0.845 | 1.184 | ok |
| perf-mixed-6 | 999.6 | 887.2 | 0.888 | 0.705 | 0.990 | 0.913 | 1.111 | ok |

OK: no case regressed; every case would have failed a slowdown of 1.271 or more

## Reference, absolute (evidence only)

| case | endpoint | p50 ms | p95 ms | min ms | max ms | bytes | Druid ms | Druid queries |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| bar_graph_sum_by_state_month | bar_graph | 85.4 | 243.2 | 54.4 | 370.0 | 159498 | 27.0 | 1 |
| line_graph_time_by_state | line_graph | 121.6 | 157.1 | 76.8 | 163.4 | 153390 | 38.5 | 2 |
| dq_data_quality_table | data_quality_table | 143.0 | 237.9 | 83.9 | 520.1 | 163081 | 80.0 | 2 |
| perf-mixed-6 | dashboard | 827.8 | 999.6 | 697.7 | 1238.9 | 1859680 | n/a | n/a |

## Candidate, absolute (evidence only)

| case | endpoint | p50 ms | p95 ms | min ms | max ms | bytes | Druid ms | Druid queries |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| bar_graph_sum_by_state_month | bar_graph | 81.1 | 253.7 | 59.6 | 389.8 | 159498 | 28.0 | 1 |
| line_graph_time_by_state | line_graph | 114.4 | 156.8 | 78.0 | 188.8 | 153390 | 39.5 | 2 |
| dq_data_quality_table | data_quality_table | 144.1 | 195.6 | 84.3 | 244.1 | 163081 | 82.0 | 2 |
| perf-mixed-6 | dashboard | 798.2 | 887.2 | 716.6 | 934 | 1856613 | n/a | n/a |
