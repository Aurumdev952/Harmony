import type { Locator, Page } from '@playwright/test';

export const E2E_DASHBOARD = { slug: 'e2e-dashboard', title: 'E2E dashboard' };

export type KnownError = { pattern: RegExp; reason: string };

export type PageCase = {
  // A stable name for reports and snapshot files.
  name: string;
  path: string;
  // Where the browser must end up, as a pathname plus hash.
  lands: RegExp;
  status?: number;
  // A visible element that proves the page rendered its own content, not
  // just the server-rendered shell.
  ready: (page: Page) => Locator;
  signedOut?: boolean;
  knownErrors?: KnownError[];
};

const NO_OBJECT_STORAGE: KnownError = {
  pattern: /HTTP 500 GET .*\/api2\/data_digest\/|page error: /,
  reason:
    'the disposable stack has no object storage, so the data digest API ' +
    'fails (WP-2c deferral; infra request for minio in the stack)',
};

/**
 * Every page that existed before the migration, under its legacy URL. This
 * table is the FE-9 contract: after the move to a single-page app each of
 * these must still land on the same page. Locale-prefixed forms are added by
 * localeCases().
 */
export const PAGES: PageCase[] = [
  {
    name: 'home',
    path: '/',
    lands: /^\/overview$/,
    ready: page => page.getByText('My Dashboards', { exact: true }),
  },
  {
    name: 'overview',
    path: '/overview',
    lands: /^\/overview$/,
    ready: page => page.getByText('My Dashboards', { exact: true }),
  },
  {
    name: 'simple-query',
    path: '/query',
    lands: /^\/advanced-query$/,
    ready: page => page.getByRole('heading', { name: 'Build Query' }),
  },
  {
    name: 'advanced-query',
    path: '/advanced-query',
    lands: /^\/advanced-query$/,
    ready: page => page.getByRole('heading', { name: 'Build Query' }),
  },
  {
    name: 'dashboard',
    path: `/dashboard/${E2E_DASHBOARD.slug}`,
    lands: new RegExp(`^/dashboard/${E2E_DASHBOARD.slug}$`),
    ready: page => page.getByText(E2E_DASHBOARD.title).first(),
  },
  {
    name: 'data-status',
    path: '/data-status',
    lands: /^\/data-status$/,
    ready: page => page.getByText('Integration Status', { exact: true }),
  },
  {
    name: 'admin',
    path: '/admin',
    lands: /^\/admin#users$/,
    ready: page => page.getByText('Role Management', { exact: true }),
  },
  {
    name: 'admin-groups',
    path: '/admin#groups',
    lands: /^\/admin#groups$/,
    ready: page => page.getByText('No groups yet'),
  },
  {
    name: 'admin-roles',
    path: '/admin#roleManagement',
    lands: /^\/admin#roleManagement$/,
    ready: page => page.getByText('Role Management', { exact: true }),
  },
  {
    name: 'admin-site-configuration',
    path: '/admin#siteConfiguration',
    lands: /^\/admin#siteConfiguration$/,
    ready: page => page.getByText('Site Configuration', { exact: true }),
  },
  {
    // Alerts are not enabled in any deployment today; the route renders the
    // not-found page with a 200 (web/server/routes/index.py).
    name: 'alerts',
    path: '/alerts',
    lands: /^\/alerts$/,
    ready: page => page.getByText('The page you are trying to access does not exist'),
  },
  {
    name: 'data-quality',
    path: '/data-quality',
    lands: /^\/data-quality$/,
    ready: page => page.getByText('Indicator', { exact: true }).first(),
  },
  {
    name: 'data-digest',
    path: '/data-digest',
    lands: /^\/data-digest#tab=pipelineOverview$/,
    // The digest itself stays blank on this stack; the client-rendered
    // navbar proves the page's bundles loaded and ran.
    ready: page => page.getByRole('button', { name: 'Analyze' }),
    knownErrors: [NO_OBJECT_STORAGE],
  },
  {
    name: 'data-upload',
    path: '/data-upload',
    lands: /^\/data-upload$/,
    ready: page => page.getByText('Data Upload', { exact: true }),
  },
  {
    name: 'indicator-setup',
    path: '/indicator-setup',
    lands: /^\/indicator-setup$/,
    // The contract stack seeds one unpublished field (seed.sql repairs it).
    ready: page => page.getByRole('row', { name: /^contract_unpublished_field / }),
  },
  {
    name: 'data-catalog',
    path: '/data-catalog',
    lands: /^\/data-catalog$/,
    ready: page => page.getByText('Yellow Fever', { exact: true }).first(),
  },
  {
    name: 'unauthorized',
    path: '/unauthorized',
    lands: /^\/unauthorized$/,
    ready: page => page.getByText('You are not authorized to perform this action'),
  },
  {
    name: 'not-found',
    path: '/no-such-page',
    lands: /^\/no-such-page$/,
    status: 404,
    ready: page => page.getByText('The page you are trying to access does not exist'),
  },
  {
    name: 'login',
    path: '/login',
    lands: /^\/login$/,
    signedOut: true,
    ready: page => page.getByRole('heading', { name: 'Sign In' }),
  },
  {
    name: 'forgot-password',
    path: '/user/forgot-password',
    lands: /^\/user\/forgot-password$/,
    signedOut: true,
    ready: page => page.getByRole('button', { name: /reset/i }),
  },
];

// Locale prefixes keep working, and the page renders in that language
// (SPEC INV-5). One page per enabled locale with translations to check.
export const LOCALE_PAGES: PageCase[] = [
  ['fr', 'Mes tableaux de bord'],
  ['pt', 'Meus painéis'],
  ['am', 'የእኔ ዳሽቦርዶች'],
].map(([locale, myDashboards]) => ({
  name: `overview-${locale}`,
  path: `/${locale}/overview`,
  lands: new RegExp(`^/${locale}/overview$`),
  ready: (page: Page) => page.getByText(myDashboards, { exact: true }),
}));

// The same pages under an explicit locale prefix (`/en/admin`), which every
// page route accepts and stored links use.
export function localeCases(locale: string): PageCase[] {
  return PAGES.filter(page => page.path !== '/' && !page.path.startsWith('/no-such')).map(
    page => ({
      ...page,
      name: `${page.name}-${locale}`,
      path: `/${locale}${page.path}`,
      lands: new RegExp(page.lands.source.replace(/^\^\\\//, `^\\/${locale}\\/`)),
    }),
  );
}
