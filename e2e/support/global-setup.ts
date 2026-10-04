import { request } from '@playwright/test';

import { ADMIN_STATE, BASE_URL, USERNAME, adminPassword } from './env';

// Signs the seeded admin in once through the same endpoint the login page
// calls, so specs that are not about login start signed in.
export default async function globalSetup(): Promise<void> {
  const context = await request.newContext({ baseURL: BASE_URL });
  const response = await context.post('/api2/authentication/login?set_cookie=true', {
    data: { email: USERNAME, password: adminPassword(), remember_me: false },
  });
  if (!response.ok()) {
    throw new Error(`admin login failed: HTTP ${response.status()}`);
  }
  await context.storageState({ path: ADMIN_STATE });
  await context.dispose();
}
