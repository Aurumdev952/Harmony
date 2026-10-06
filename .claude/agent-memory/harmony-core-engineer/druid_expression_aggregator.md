---
name: druid-expression-aggregator
description: Traps in Druid's native `expression` aggregator (0.23 and 38), learned replacing the aggregateLast extension for LAST_VALUE in WP-8a N3
metadata:
  type: reference
---

Druid's `expression` aggregator (`ExpressionLambdaAggregatorFactory`, registered in 0.23.0 and still in 38) can replace custom aggregation extensions. The 0.23 docs page does not show it; read the 0.23.0 source instead. Verified live on 2026-10-05:

- **Scalar and array use.** 0.23 rejects an expression in which a variable is used both as an array (`array_offset(x, 0)`) and bare (`x` returned as a branch value): "used as both scalar and array variables". Always return `array(array_offset(x, 0), array_offset(x, 1))`, never `x`.
- **`initialValue` must parse to a literal.** `array(-9007199254740992.0, 0.0)` constant-folds, so it works.
- **`array()` typing.** In 0.23, `array()` types its output from the first argument. Cast `__time` to `DOUBLE` before pairing it with a double.
- **Bindings.** `combine` binds `__acc` and the aggregator's own `name`, so the expression embeds the name. In Harmony, pydruid re-keys aggregations after calculations build them (ComplexCalculation suffixes), so build the aggregator where pydruid assigns names: `_build_aggregator_workaround` in `db/druid/util.py`.
- **Null switches.**
  - `isNullUnlessAggregated` defaults to the null mode, so under SQL-compatible nulls an empty group gives null. Set it to false to keep legacy 0.
  - Set `shouldCombineAggregateNullInputs: false`, or combine sees null partials.
- **Post-aggregators.** groupBy post-aggregators (AVERAGE's ratio) saw finalized values in both 0.23 and 38.

**How to apply:** WP-8b deletes the `extension` branch in `db/druid/aggregations/last_value_aggregation.py`. Any other extension aggregator can use the same pattern, proven against a reference built from core aggregators (`tests/druid/test_last_value_live.py`).

Related: [[tooling-traps]]
