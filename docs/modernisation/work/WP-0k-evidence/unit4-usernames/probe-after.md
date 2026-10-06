| Step (run `after`) | Status | JWT identity | Signed in as |
|---|---|---|---|
| log in typing the username in lower case | 200 | `Mixed.Case.after@harmony.invalid` | Mixed.Case.after@harmony.invalid |
| admin invites the look-alike jane_doe.after@harmony.invalid | 200 | `` |  |
| the look-alike registers | 200 | `jane_doe.after@harmony.invalid` | jane_doe.after@harmony.invalid |
| the look-alike logs in with its own password | 200 | `jane_doe.after@harmony.invalid` | jane_doe.after@harmony.invalid |
| the older account logs in | 200 | `jane.doe.after@harmony.invalid` | jane.doe.after@harmony.invalid |
| admin invites MIXED.CASE.AFTER@HARMONY.INVALID (exists as Mixed.Case.after@harmony.invalid) | 400 | `` | accounts equal to it ignoring case: 1 |
