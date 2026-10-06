import { randomBytes } from 'crypto';

import { signIn } from '../support/auth';
import { expect, test } from '../support/fixtures';
import { latestMail, linkIn } from '../support/mailbox';

// One invited account walks the e-mail flows in order: an administrator
// invites it, the invitee registers from the e-mailed link, then forgets
// the password and resets it from a second e-mailed link.
test.describe.configure({ mode: 'serial' });
// The cases type passwords, which a trace would record.
test.use({ trace: 'off' });

const run = randomBytes(4).toString('hex');
const EMAIL = `e2e-invitee-${run}@harmony.invalid`;
// The register form wants an upper and lower case letter, a digit and a symbol.
const password = (): string => `Aa1!${randomBytes(12).toString('hex')}`;
const FIRST_PASSWORD = password();
const NEW_PASSWORD = password();

test.describe('account e-mail flows @smoke @auth', () => {
  test('an administrator invites a user, who registers from the e-mailed link', async ({
    page,
    signedOutPage,
  }) => {
    await page.goto('/admin#users');
    await page.getByRole('textbox', { name: 'Enter name' }).fill('Ina Vitee');
    await page.getByRole('textbox', { name: 'Enter email' }).fill(EMAIL);
    await page.getByRole('button', { name: 'invite user' }).click();
    await expect(page.getByText('Successfully invited user.')).toBeVisible();
    await expect(page.getByRole('row', { name: new RegExp(`${EMAIL} Pending`) })).toBeVisible();

    const invite = await latestMail(EMAIL, /Invite/);
    const invitee = await signedOutPage();
    await invitee.goto(linkIn(invite, /^\/zen\/register$/));
    await expect(invitee.getByLabel('Email Address')).toHaveValue(EMAIL);
    await invitee.getByLabel('First Name').fill('Ina');
    await invitee.getByLabel('Last Name').fill('Vitee');
    await invitee.getByLabel('Password').fill(FIRST_PASSWORD);
    await invitee.getByRole('button', { name: 'register' }).click();

    await expect(invitee).toHaveURL(/\/overview$/);
    await expect(invitee.getByRole('heading', { name: 'Welcome, Ina Vitee' })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('row', { name: new RegExp(`${EMAIL} Active`) })).toBeVisible();
  });

  test('a user who forgot the password resets it from the e-mailed link', async ({
    signedOutPage,
  }) => {
    const user = await signedOutPage();
    await user.goto('/user/forgot-password');
    await user.getByLabel('Email Address').fill(EMAIL);
    await user.getByRole('button', { name: 'send reset link' }).click();
    await expect(user.getByText('the password reset link has been shared')).toBeVisible();

    const reset = await latestMail(EMAIL, /^Reset Password/);
    await user.goto(linkIn(reset, /^\/user\/reset-password$/));
    await user.getByLabel('New Password').fill(NEW_PASSWORD);
    await user.getByRole('button', { name: 'change password' }).click();
    await expect(user).toHaveURL(/\/login/);
    await expect(user.getByRole('heading', { name: 'Sign In' })).toBeVisible();

    const fresh = await signedOutPage();
    await signIn(fresh, EMAIL, FIRST_PASSWORD);
    await expect(fresh.getByText('Incorrect username and/or password.')).toBeVisible();
    await signIn(fresh, EMAIL, NEW_PASSWORD);
    await expect(fresh).toHaveURL(/\/overview$/);
    await expect(fresh.getByRole('heading', { name: 'Welcome, Ina Vitee' })).toBeVisible();
  });
});
