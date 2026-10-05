| Pre-WP-0k cookie | JWT identity | Signed in as |
|---|---|---|
| typed in lower case at login | `mixed.case.before@harmony.invalid` | mixed.case.before@harmony.invalid |
| typed as stored | `Mixed.Case.before@harmony.invalid` | Mixed.Case.before@harmony.invalid |
| minted by the look-alike's registration | `jane_doe.before@harmony.invalid` | jane_doe.before@harmony.invalid |
| the older account | `jane.doe.before@harmony.invalid` | jane.doe.before@harmony.invalid |
| a LIKE wildcard | `jane%before@harmony.invalid` | anonymous |
| equal ignoring case to two accounts | `MIXED.CASE.BEFORE@HARMONY.INVALID` | anonymous |
