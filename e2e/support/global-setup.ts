import { chmodSync } from 'fs';

import { request } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';

import { ADMIN_STATE, BASE_URL, USERNAME, adminPassword } from './env';
import { E2E_DASHBOARD } from './pages';

export function emptyDashboardSpec(title: string): Record<string, unknown> {
  return {
    commonSettings: {
      filterSettings: {
        enabledCategories: [],
        enabledFilterHierarchy: [],
        excludedTiles: [],
        items: [],
        visible: false,
      },
      groupingSettings: { enabledCategories: [], excludedTiles: [], items: [], visible: false },
      panelAlignment: 'LEFT',
    },
    items: [],
    legacy: false,
    options: { columnCount: 100, title },
    version: '2023-06-30',
  };
}

async function ensureDashboard(api: APIRequestContext): Promise<void> {
  const existing = await api.get('/api2/dashboard', {
    params: { where: JSON.stringify({ slug: E2E_DASHBOARD.slug }) },
  });
  if ((await existing.json()).length > 0) {
    return;
  }
  const created = await api.post('/api2/dashboard', {
    data: { slug: E2E_DASHBOARD.slug, specification: emptyDashboardSpec(E2E_DASHBOARD.title) },
  });
  if (!created.ok()) {
    throw new Error(`creating ${E2E_DASHBOARD.slug} failed: HTTP ${created.status()}`);
  }
  const { $uri: uri } = await created.json();
  const item = await api.post(`${uri}/add_item`, {
    data: {
      id: 'e2e-text-holder',
      item: {
        autosize: true,
        text: '<p>Text tile written by the e2e setup.</p>',
        type: 'TEXT_ITEM',
      },
      position: { columnCount: 50, rowCount: 4, x: 0 },
    },
  });
  if (!item.ok()) {
    throw new Error(`adding a tile to ${E2E_DASHBOARD.slug} failed: HTTP ${item.status()}`);
  }
}

// Signs the seeded admin in once through the same endpoint the login page
// calls, so specs that are not about login start signed in, and creates the
// dashboard the page table opens.
export default async function globalSetup(): Promise<void> {
  const api = await request.newContext({ baseURL: BASE_URL });
  const response = await api.post('/api2/authentication/login?set_cookie=true', {
    data: { email: USERNAME, password: adminPassword(), remember_me: false },
  });
  if (!response.ok()) {
    throw new Error(`admin login failed: HTTP ${response.status()}`);
  }
  await api.storageState({ path: ADMIN_STATE });
  chmodSync(ADMIN_STATE, 0o600);
  await ensureDashboard(api);
  await api.dispose();
}
