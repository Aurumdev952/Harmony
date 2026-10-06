import { randomBytes } from 'crypto';

import { expect, test } from '../support/fixtures';

// A file in the Zenysis base format: group-bys, a date, then indicators.
const CSV = 'StateName,date,e2e_upload_cases\nAcre,2023-01-01,4\nPará,2023-02-01,7\n';

test.describe('data upload @smoke @upload', () => {
  test('a CSV goes through upload, mapping and review and becomes a queued source', async ({
    page,
  }) => {
    const source = `E2E upload ${randomBytes(4).toString('hex')}`;
    await page.goto('/data-upload');
    await page.getByRole('button', { name: '+ Add source' }).click();
    const wizard = page.getByRole('dialog', { name: 'Prompt Modal' });
    await expect(wizard.getByRole('heading', { name: 'Add data' })).toBeVisible();
    await expect(wizard.getByRole('button', { name: 'mapping' })).toBeDisabled();

    await wizard.getByRole('textbox', { name: 'Data Source Name' }).fill(source);
    await wizard.locator('input[type=file]').setInputFiles({
      buffer: Buffer.from(CSV),
      mimeType: 'text/csv',
      name: 'e2e-upload.csv',
    });
    await expect(wizard.getByText('File format passes validation')).toBeVisible();

    await wizard.getByRole('button', { name: 'mapping' }).click();
    // Each column becomes a card: the dimension matched to State, the date,
    // and the unknown column proposed as a new indicator.
    await expect(wizard.getByRole('heading', { name: 'State', exact: true })).toBeVisible();
    await expect(wizard).toContainText('Input name: StateName');
    await expect(wizard).toContainText('Input name: date');
    await expect(wizard).toContainText('Input name: e2e_upload_casesMarked as a new indicator');

    await wizard.getByRole('button', { name: 'review' }).click();
    const preview = wizard.getByRole('table', { name: 'table' });
    await expect(preview.getByRole('columnheader')).toHaveText([
      'State',
      'Date',
      'e2e_upload_cases',
    ]);
    await expect(preview).toContainText('Acre2023-01-014Pará2023-02-017');

    await wizard.getByRole('button', { name: 'complete setup' }).click();
    await expect(page.getByText('Succesfully created new source')).toBeVisible();
    const row = page.getByRole('row', { name: new RegExp(`^${source} CSV `) });
    await expect(row).toContainText('1 new indicator');
    await expect(row).toContainText('queued');
  });
});
