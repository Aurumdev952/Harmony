# Requests to the lead: `scripts/create_user.py` (owned by the lead)

## 1. Done (299c632)

`create_user` found the existing account with an `ILIKE` pattern, so `-o john_doe@…` overwrote `john.doe@…`. The lead replaced it with `find_user_by_username` and `username_taken`.

## 2. Round 3 (reviewer finding 7): name the target by its exact spelling

`find_user_by_username` is sign-in's rule and prefers an active account, so `-o dup.shell@…` (a pending account spelled exactly so) picks its active twin `Dup.Shell@…` and renames it to `dup.shell@…`, which then collides with the pending account's username. A caller naming an account means the exact spelling, whatever its status. WP-0k adds `find_named_account` for this (exact spelling, any status; else the one account equal ignoring case; else None), used by `try_get_user` and role assignment.

Change, in `create_user`:

```python
-from web.server.security.usernames import find_user_by_username, username_taken
+from web.server.security.usernames import find_named_account, username_taken
...
-    existing_user = find_user_by_username(username, session)
+    existing_user = find_named_account(username, session)
```

The refusal below it (`if not existing_user and username_taken(...)`) stays: with two accounts equal ignoring case and neither spelled exactly, nothing is named.

Check: add to `tests/web/usernames/test_account_targets.py`

```python
def test_create_user_script_overwrites_the_exactly_spelled_pending_account(
    app, create_user
):
    create_user('dup.shell@moh.gov.rw', overwrite=True)

    assert _column(app, 11, 'first_name') == 'Script'
    assert _column(app, 10, 'first_name') == 'First'
    assert _column(app, 10, 'username') == 'Dup.Shell@moh.gov.rw'
```

It fails today (the script overwrites account 10 and the rename collides) and passes after.
