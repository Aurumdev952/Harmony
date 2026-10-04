---
name: review-gate-arithmetic
description: When a WP tool prints a threshold verdict (for example the phase 7 browser gate at 5%), check that it compares unrounded counts and handles an empty input
metadata:
  type: feedback
---

Probe every threshold verdict at the boundary and with zero input. In WP-0g, `_pct` rounded to one decimal before the `<= 5.0` check, so 504 of 10000 sessions (5.04%) printed "within the 5% gate". Zero parsed sessions also printed "within". Both were found by building synthetic logs in a /tmp probe, not by the builder's tests.

**Why:** these verdicts feed human decision records (decision 0002), and a wrong "within" there goes unnoticed.
**How to apply:** for any report or gate, ask for raw counts in the data structure and round only for display. Ask for a boundary test and an empty-input test. Related: [[review-traps]].
