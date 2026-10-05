| queryUrl sent (Host: attacker.invalid) | Status | Link in the mail |
|---|---|---|
| `https://real.org/advanced-query#h=d41d8cd98f00b204` | 200 | `https://harmony_demo.zenysis.com/advanced-query#h=d41d8cd98f00b204` |
| `https://attacker.invalid/advanced-query#h=d41d8cd98f00b204` | 200 | `https://harmony_demo.zenysis.com/advanced-query#h=d41d8cd98f00b204` |
| `https://attacker.invalid/fr/advanced-query#h=d41d8cd98f00b204` | 200 | `https://harmony_demo.zenysis.com/fr/advanced-query#h=d41d8cd98f00b204` |
| `https://attacker.invalid/phish` | 200 | `https://harmony_demo.zenysis.com/advanced-query` |
| `https://real.org/advanced-query#h="><a href="https://attacker.invalid/">x</a>` | 400 | `` |
