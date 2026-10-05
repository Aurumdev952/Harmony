import { readFileSync, statSync } from 'fs';

// Set by e2e/run.sh from tests/contract/stack/stack.sh env. The password is
// generated per stack into a mode-600 file and is read here, never passed
// through the environment or printed (SPEC INV-6).
function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not set; start the suite with e2e/run.sh`);
  }
  return value;
}

export const BASE_URL = required('E2E_BASE_URL');
export const USERNAME = required('E2E_USERNAME');
export const PROJECT = process.env.E2E_PROJECT ?? 'harmony-wp2e-e2e';

export function adminPassword(): string {
  const file = required('E2E_CREDENTIALS_FILE');
  const { mode, uid } = statSync(file);
  if ((mode & 0o077) !== 0 || uid !== process.getuid?.()) {
    throw new Error(`${file} must be owned by you with mode 600`);
  }
  const match = /^CONTRACT_PASSWORD=([0-9a-f]{64})$/m.exec(readFileSync(file, 'utf8'));
  if (!match) {
    throw new Error(`${file} has no CONTRACT_PASSWORD line`);
  }
  return match[1];
}

// Signed-in browser state for the seeded site admin. It holds a session
// cookie, so run.sh puts it in the stack's 0700 runtime directory (inside the
// visual container, in that container's own /tmp) and deletes it on down.
export const ADMIN_STATE = required('E2E_ADMIN_STATE');
