import { SIGNED_OUT, signIn } from '../support/auth';
import { USERNAME, adminPassword } from '../support/env';
import { expect, test } from '../support/fixtures';

// These cases type the admin password, which a trace would record.
test.use({ storageState: SIGNED_OUT, trace: 'off' });

test.describe('login @smoke @login', () => {
  test('a signed-out visit to a page redirects to the login page', async ({ page }) => {
    await page.goto('/overview');

    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole('heading', { name: 'Sign In' })).toBeVisible();
  });

  test('signing in lands on the overview with an HttpOnly session cookie', async ({
    context,
    page,
  }) => {
    await signIn(page, USERNAME, adminPassword());

    await expect(page).toHaveURL(/\/overview$/);
    await expect(page.getByText('Welcome, Contract', { exact: false })).toBeVisible();
    const session = (await context.cookies()).find(cookie => cookie.name === 'accessKey');
    expect(session?.httpOnly).toBe(true);
  });

  test('a wrong password keeps the user on the login page', async ({ context, page }) => {
    await signIn(page, USERNAME, 'not-the-password');

    await expect(page.getByText('Incorrect username and/or password.')).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
    const cookies = await context.cookies();
    expect(cookies.some(cookie => cookie.name === 'accessKey')).toBe(false);
  });

  test('signing out ends the session', async ({ page }) => {
    await signIn(page, USERNAME, adminPassword());
    await expect(page).toHaveURL(/\/overview$/);

    await page.getByRole('button', { name: /Contract/ }).click();
    await page.getByText('Sign out', { exact: true }).click();

    await expect(page).toHaveURL(/\/login/);
    await page.goto('/overview');
    await expect(page).toHaveURL(/\/login/);
  });
});
