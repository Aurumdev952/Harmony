# Request to the lead: `scripts/create_user.py` (owned by the lead)

`create_user` finds the existing account with `find_one_by_fields(User, False, {'username': username})`, an `ILIKE` pattern, so `scripts/create_user.py -u john_doe@… -o` overwrites `john.doe@…`, and a username equal to another ignoring case creates a case-only twin. Replace that line with:

```python
    # Equality ignoring case, never a LIKE pattern: `-o john_doe@…` must not
    # overwrite `john.doe@…`. A username two accounts equal, neither exactly,
    # names none of them, and a new account may not add a third.
    session = transaction.run_raw()
    existing_user = find_user_by_username(username, session)
    if not existing_user and username_taken(username, session):
        message = (
            'Another account has username \'%s\' in another case. '
            'Use its exact username.' % username
        )
        LOG.error(message)
        raise ValueError(message)
```

and import `from web.server.security.usernames import find_user_by_username, username_taken`.

Check: in `tests/web/usernames/test_account_targets.py`, the tests marked `PENDING_SCRIPT_CHANGE` (strict xfail today) pass; remove the marks in the same commit.
