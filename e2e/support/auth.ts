import type { Page } from '@playwright/test';

export const SIGNED_OUT = { cookies: [], origins: [] };

export async function signIn(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email Address').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'sign in' }).click();
}
