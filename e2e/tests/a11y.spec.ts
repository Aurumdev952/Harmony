import { readFileSync, writeFileSync } from 'fs';
import path from 'path';

import AxeBuilder from '@axe-core/playwright';

import { SIGNED_OUT } from '../support/auth';
import { expect, test } from '../support/fixtures';
import { PAGES } from '../support/pages';

// Today's serious and critical axe violations, per page and rule, as node
// counts. FE-8 is met when WP-7c to 7e have driven this file to `{}`. Until
// then a page may not gain a rule or a node, and a page that improves must
// shrink its entry, so the baseline never holds slack a regression could
// hide in. Regenerate with E2E_A11Y_UPDATE=1 (review the diff); a run limited
// with --grep rewrites only the pages it ran.
const BASELINE_FILE = path.join(__dirname, '..', 'a11y', 'baseline.json');
const UPDATE = process.env.E2E_A11Y_UPDATE === '1';
const BLOCKING = new Set(['serious', 'critical']);

type Counts = Record<string, number>;

const baseline: Record<string, Counts> = JSON.parse(readFileSync(BASELINE_FILE, 'utf8'));
const PAGE_NAMES = new Set(PAGES.map(({ name }) => name));
// What an update run writes: the pages it did not run keep their entries, and
// entries for pages no longer in the table go.
const updated: Record<string, Counts> = Object.fromEntries(
  Object.entries(baseline).filter(([name]) => PAGE_NAMES.has(name)),
);

function compare(page: string, now: Counts): { worse: string[]; better: string[] } {
  const before = baseline[page] ?? {};
  const rules = [...new Set([...Object.keys(before), ...Object.keys(now)])].sort();
  const worse: string[] = [];
  const better: string[] = [];
  for (const rule of rules) {
    const [was, is] = [before[rule] ?? 0, now[rule] ?? 0];
    if (is > was) {
      worse.push(`${rule}: ${was} -> ${is} nodes`);
    } else if (is < was) {
      better.push(`${rule}: ${was} -> ${is} nodes`);
    }
  }
  return { better, worse };
}

if (UPDATE) {
  // One worker, so the file is written once with every page.
  test.describe.configure({ mode: 'serial' });
  test.afterAll(() => {
    const sorted = Object.fromEntries(Object.keys(updated).sort().map(k => [k, updated[k]]));
    writeFileSync(BASELINE_FILE, `${JSON.stringify(sorted, null, 2)}\n`);
  });
}

test.describe('axe baseline at 1440 px @a11y', () => {
  test('the baseline names only pages in the page table', () => {
    expect(Object.keys(baseline).filter(name => !PAGE_NAMES.has(name))).toEqual([]);
  });

  for (const pageCase of PAGES) {
    test.describe(pageCase.name, () => {
      if (pageCase.signedOut) {
        test.use({ storageState: SIGNED_OUT });
      }

      test(`${pageCase.path} has no new serious or critical violations`, async ({
        appErrors,
        page,
      }) => {
        pageCase.knownErrors?.forEach(({ pattern, reason }) => appErrors.allow(pattern, reason));
        await page.goto(pageCase.path);
        await expect(pageCase.ready(page)).toBeVisible();

        const { violations } = await new AxeBuilder({ page }).analyze();
        const blocking = violations.filter(v => BLOCKING.has(v.impact ?? ''));
        const now: Counts = Object.fromEntries(
          blocking.map(v => [v.id, v.nodes.length] as const).sort(),
        );
        if (UPDATE) {
          if (Object.keys(now).length > 0) {
            updated[pageCase.name] = now;
          } else {
            delete updated[pageCase.name];
          }
          return;
        }

        const { better, worse } = compare(pageCase.name, now);
        const detail = blocking
          .filter(v => worse.some(line => line.startsWith(`${v.id}:`)))
          .map(v => `${v.id} (${v.impact}): ${v.help}\n  ${v.nodes.map(n => n.target).join('\n  ')}`);
        expect(worse, `new violations on ${pageCase.path}\n${detail.join('\n')}`).toEqual([]);
        expect(
          better,
          `${pageCase.path} improved; shrink its entry in e2e/a11y/baseline.json`,
        ).toEqual([]);
      });
    });
  }
});
