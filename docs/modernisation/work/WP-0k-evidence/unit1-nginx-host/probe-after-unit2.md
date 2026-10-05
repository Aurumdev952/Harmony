| Path | Host header | Request target | Extra header | Status | Location | Mailed link |
|---|---|---|---|---|---|---|
| direct gunicorn | `attacker.invalid` | `(origin-form)` | `` | 200 | `` | Reset Password: Zenysis -> https://harmony_demo.zenysis.com/user/reset-password?token=<redacted> |
| direct gunicorn | `real.org:@attacker.invalid` | `(origin-form)` | `` | 200 | `` | Reset Password: Zenysis -> https://harmony_demo.zenysis.com/user/reset-password?token=<redacted> |
| direct gunicorn | `real.org` | `(origin-form)` | `SCRIPT_NAME: @attacker.invalid` | 500 | `` | (no mail) |
| direct gunicorn | `real.org` | `/@attacker.invalid/api2/authentication/forgot_password` | `SCRIPT_NAME: @attacker.invalid` | 200 | `` | Reset Password: Zenysis -> https://harmony_demo.zenysis.com/user/reset-password?token=<redacted> |
| nginx https | `real.org` | `(origin-form)` | `` | 200 | `` | Reset Password: Zenysis -> https://harmony_demo.zenysis.com/user/reset-password?token=<redacted> |
| nginx https | `attacker.invalid` | `(origin-form)` | `` | 503 | `` | (no mail) |
| nginx https | `real.org:@attacker.invalid` | `(origin-form)` | `` | 400 | `` | (no mail) |
| nginx https | `real.org:443@attacker.invalid` | `(origin-form)` | `` | 400 | `` | (no mail) |
| nginx https | `real.org@attacker.invalid` | `(origin-form)` | `` | 400 | `` | (no mail) |
| nginx https | `Real.ORG:@attacker.invalid` | `(origin-form)` | `` | 400 | `` | (no mail) |
| nginx https | `real.org:8443` | `(origin-form)` | `` | 200 | `` | Reset Password: Zenysis -> https://harmony_demo.zenysis.com/user/reset-password?token=<redacted> |
| nginx https | `real.org.` | `(origin-form)` | `` | 200 | `` | Reset Password: Zenysis -> https://harmony_demo.zenysis.com/user/reset-password?token=<redacted> |
| nginx https | `real.org` | `https://attacker.invalid/api2/authentication/forgot_password` | `` | 503 | `` | (no mail) |
| nginx https | `real.org` | `https://real.org:@attacker.invalid/api2/authentication/forgot_password` | `` | 400 | `` | (no mail) |
| nginx https | `attacker.invalid` | `https://real.org/api2/authentication/forgot_password` | `` | 200 | `` | Reset Password: Zenysis -> https://harmony_demo.zenysis.com/user/reset-password?token=<redacted> |
| nginx https | `real.org` | `(origin-form)` | `X-Forwarded-Host: attacker.invalid` | 200 | `` | Reset Password: Zenysis -> https://harmony_demo.zenysis.com/user/reset-password?token=<redacted> |
| nginx https | `real.org` | `(origin-form)` | `SCRIPT_NAME: @attacker.invalid` | 200 | `` | Reset Password: Zenysis -> https://harmony_demo.zenysis.com/user/reset-password?token=<redacted> |
| nginx https | `real.org` | `(origin-form)` | `Script-Name: @attacker.invalid` | 200 | `` | Reset Password: Zenysis -> https://harmony_demo.zenysis.com/user/reset-password?token=<redacted> |
| nginx https | `real.org` | `/@attacker.invalid/api2/authentication/forgot_password` | `SCRIPT_NAME: @attacker.invalid` | 405 | `` | (no mail) |
| nginx http | `real.org` | `(origin-form)` | `` | 301 | `https://real.org/api2/authentication/forgot_password` | (no mail) |
| nginx http | `real.org:@attacker.invalid` | `(origin-form)` | `` | 400 | `` | (no mail) |
| nginx http | `attacker.invalid` | `(origin-form)` | `` | 503 | `` | (no mail) |
