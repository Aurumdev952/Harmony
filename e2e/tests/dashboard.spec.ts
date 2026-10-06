import { randomBytes } from 'crypto';
import { readFileSync } from 'fs';

import type { Locator, Page } from '@playwright/test';

import { CASES, STATE, buildQuery, selectVisualization } from '../support/aqt';
import { BASE_URL } from '../support/env';
import { expect, test } from '../support/fixtures';
import { latestMail, linkIn } from '../support/mailbox';

// One dashboard, made in the first case, goes through the flows a user
// takes with it: create from a query, open, edit, share by link and e-mail,
// export, and present. The cases run in order on it.
test.describe.configure({ mode: 'serial' });

const run = randomBytes(4).toString('hex');
const TITLE = `E2E query ${run}`;
const NOTE = `Note written by the e2e suite (${run}).`;
let dashboardPath = '';

// The text tile's Jodit editor fetches js-beautify and ace from cdnjs when it
// opens (Jodit's default source-mode config; TextEditView/JoditEditor.jsx).
// The stack has no route out, so both fail and surface as bare Event errors.
const EDITOR_CDN = [
  {
    pattern: new RegExp(
      '^external request blocked: https://cdnjs\\.cloudflare\\.com/ajax/libs/(js-beautify|ace)/',
    ),
    reason: 'Jodit loads js-beautify and ace from cdnjs at runtime (request to frontend-platform)',
  },
  {
    pattern: /^page error: Event$/,
    reason: 'the failed cdnjs script loads above surface as uncaught Event errors',
  },
];

function shareModal(page: Page): Locator {
  return page.getByRole('dialog', { name: 'Prompt Modal' }).filter({ hasText: 'Share' });
}

async function openShare(page: Page, tab: 'link' | 'email' | 'download'): Promise<Locator> {
  await page.goto(dashboardPath);
  await expect(page.getByRole('heading', { name: TITLE })).toBeVisible();
  await page.getByRole('button', { name: 'Share' }).first().click();
  await page.getByRole('option', { name: tab }).click();
  return shareModal(page);
}

test.describe('dashboard flows @smoke @dashboard', () => {
  test('a query from Analyze goes onto a new dashboard, which opens with the chart', async ({
    page,
  }) => {
    await buildQuery(page, { groups: [STATE], indicators: [CASES] });
    await selectVisualization(page, 'BAR');
    await page.getByRole('button', { name: /add to dashboard/i }).click();
    const picker = page.getByRole('dialog', { name: 'Prompt Modal' });
    await picker.getByRole('button', { name: 'Create Dashboard' }).click();
    await picker.getByRole('textbox').fill(TITLE);
    await picker.getByRole('button', { name: 'create' }).click();
    await expect(picker.getByText(`Your query has been saved to ${TITLE}.`)).toBeVisible();
    await picker.getByRole('button', { name: 'go to dashboard' }).click();

    await expect(page).toHaveURL(/\/dashboard\/e2e_query_[0-9a-f]+$/);
    dashboardPath = new URL(page.url()).pathname;
    await expect(page.getByRole('heading', { name: TITLE })).toBeVisible();
    const chart = page.getByRole('figure', { name: 'bar chart' });
    await expect(chart).toBeVisible();
    await expect(chart.getByText('Acre', { exact: true })).toBeVisible();

    await page.goto('/overview');
    await page.getByRole('textbox', { name: 'Search dashboard by name' }).fill(run);
    await page.getByRole('row', { name: new RegExp(`^${TITLE} `) }).click();
    await expect(page).toHaveURL(new RegExp(`${dashboardPath}$`));
    await expect(page.getByRole('figure', { name: 'bar chart' })).toBeVisible();
  });

  test('a text tile added in the editor is saved and survives a reload', async ({
    appErrors,
    page,
  }) => {
    EDITOR_CDN.forEach(({ pattern, reason }) => appErrors.allow(pattern, reason));
    await page.goto(dashboardPath);
    await page.getByRole('button', { name: 'Add Content' }).first().click();
    await page.getByRole('option', { name: 'Add Text' }).click();
    await page.getByRole('button', { name: 'add text' }).last().click();
    // The editor's confirm and cancel buttons have no accessible name.
    const editor = page.locator('.gd-dashboard-text-edit-view');
    await editor.locator('[contenteditable="true"]').click();
    await page.keyboard.type(NOTE);
    await editor.locator('.gd-dashboard-text-edit-view__icon_btn--save').click();
    await expect(editor).toHaveCount(0);
    await expect(page.getByText(NOTE)).toBeVisible();
    await page.getByRole('button', { name: 'Save' }).click();

    await page.reload();
    await expect(page.getByText(NOTE)).toBeVisible();
    await expect(page.getByRole('figure', { name: 'bar chart' })).toBeVisible();
  });

  test('the share link is the dashboard URL and opens it', async ({ page }) => {
    const modal = await openShare(page, 'link');

    const link = modal.getByRole('textbox');
    await expect(link).toHaveValue(`${BASE_URL}${dashboardPath}`);
    await page.goto(await link.inputValue());
    await expect(page.getByText(NOTE)).toBeVisible();
  });

  test('sharing by e-mail sends the recipient a link to the dashboard', async ({ page }) => {
    const recipient = `e2e-share-${run}@harmony.invalid`;
    const modal = await openShare(page, 'email');
    const to = modal.getByRole('textbox').first();
    await to.fill(recipient);
    await to.press('Enter');
    await modal.getByRole('button', { name: 'send email' }).click();
    // The recipient has no account, so the app asks before sending.
    const confirm = page.getByRole('dialog', { name: 'Prompt Modal' }).filter({
      hasText: 'Confirm Sharing',
    });
    await confirm.getByRole('button', { name: 'send' }).click();

    const mail = await latestMail(recipient, /^Dashboard Analysis Shared$/);
    expect(new URL(linkIn(mail, new RegExp(`^${dashboardPath}$`))).pathname).toBe(dashboardPath);
  });

  for (const [format, magic] of [
    ['PDF', '%PDF-'],
    ['JPEG', '\xff\xd8\xff'],
  ] as const) {
    test(`download exports a ${format} through the renderer`, async ({ page }) => {
      const modal = await openShare(page, 'download');
      await modal.getByRole('checkbox', { name: format }).click();
      const download = page.waitForEvent('download');
      await modal.getByRole('button', { name: 'download (1)' }).click();

      const file = await download;
      expect(file.suggestedFilename()).toBe(`${TITLE}.${format.toLowerCase()}`);
      const head = readFileSync((await file.path())!).subarray(0, magic.length);
      expect(head.toString('latin1')).toBe(magic);
    });
  }

  // Last, so that a failure here cannot keep the share and export cases from
  // running (the cases run in order on one dashboard).
  test('present mode hides the editing controls and keeps the tiles', async ({ page }) => {
    await page.goto(dashboardPath);
    await expect(page.getByRole('heading', { name: TITLE })).toBeVisible();
    // The switch has no accessible name (aria-toggle-field-name in the a11y
    // baseline), so it is found by its container.
    const toggle = page.locator('.gd-dashboard-header__presentation-toggle [role="switch"]');
    const addContent = page.getByRole('button', { name: 'Add Content' });
    await expect(addContent.first()).toBeVisible();

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-checked', 'true');
    await expect(addContent).toHaveCount(0);
    await expect(page.getByText(NOTE)).toBeVisible();
    await expect(page.getByRole('figure', { name: 'bar chart' })).toBeVisible();

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    await expect(addContent.first()).toBeVisible();
  });
});
