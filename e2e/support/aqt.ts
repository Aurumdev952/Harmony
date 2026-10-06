import { expect } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';

// Indicators the e2e stack's Data Catalog holds (see e2e/stack/seed.sql).
export const CASES = 'Cases';
export const DEATHS = 'Deaths (e2e)';

export type Group = ['Geography', 'State'] | ['Date Group', 'Month'];
export const STATE: Group = ['Geography', 'State'];
export const MONTH: Group = ['Date Group', 'Month'];

export type QuerySetup = { indicators: string[]; groups: Group[] };

// The selector popovers close on an outside click; Escape does nothing. The
// lower part of the query-building panel is empty at 1440 x 900.
async function closePopover(page: Page): Promise<void> {
  await page.mouse.click(150, 760);
  await expect(page.getByRole('dialog')).toHaveCount(0);
}

function selectorButton(page: Page, section: 'indicators' | 'groups'): Locator {
  return page.locator('.query-part-selector').nth(section === 'indicators' ? 0 : 1);
}

export async function addIndicator(page: Page, shortName: string): Promise<void> {
  await selectorButton(page, 'indicators').click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('menuitem', { name: /^Yellow Fever/ }).click();
  await dialog.getByRole('menuitem', { exact: true, name: shortName }).click();
  await closePopover(page);
}

export async function addGroup(page: Page, [category, item]: Group): Promise<void> {
  await selectorButton(page, 'groups').click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('menuitem', { name: new RegExp(`^${category}`) }).click();
  await dialog.getByRole('menuitem', { exact: true, name: item }).click();
  await closePopover(page);
}

export async function buildQuery(page: Page, { groups, indicators }: QuerySetup): Promise<void> {
  await page.goto('/advanced-query');
  await expect(page.getByRole('heading', { name: 'Build Query' })).toBeVisible();
  for (const indicator of indicators) {
    await addIndicator(page, indicator);
  }
  for (const group of groups) {
    await addGroup(page, group);
  }
}

export function resultContainer(page: Page): Locator {
  return page.locator('.aqt-query-result-container');
}

/**
 * Picks a visualization from the full picker. When the query meets the
 * type's requirements the picker closes and the toolbar shows "Show all"
 * again; otherwise it stays open on the requirements panel.
 */
export async function selectVisualization(page: Page, type: string): Promise<void> {
  const option = page.getByTestId(`aqt-explore-view-viz-option__${type}`);
  if (!(await option.isVisible())) {
    await page.getByText('Show all', { exact: true }).click();
  }
  await option.click();
  await expect(page.getByText('Show all', { exact: true })).toBeVisible();
}
