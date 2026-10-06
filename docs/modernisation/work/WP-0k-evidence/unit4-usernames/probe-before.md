| Step (run `before2`) | Status | JWT identity | Signed in as |
|---|---|---|---|
| log in typing the username in lower case | 200 | `mixed.case.before2@harmony.invalid` | Mixed.Case.before2@harmony.invalid |
| admin invites the look-alike jane_doe.before2@harmony.invalid | 200 | `` |  |
| the look-alike registers | 200 | `jane_doe.before2@harmony.invalid` | jane.doe.before2@harmony.invalid |
| the look-alike logs in with its own password | 400 | `` | anonymous |
| the older account logs in | 200 | `jane.doe.before2@harmony.invalid` | jane.doe.before2@harmony.invalid |
| admin invites MIXED.CASE.BEFORE2@HARMONY.INVALID (exists as Mixed.Case.before2@harmony.invalid) | 200 | `` | accounts equal to it ignoring case: 2 |
