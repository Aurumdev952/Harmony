// Serious and critical axe violations of one page, as node counts per rule.
export type Counts = Record<string, number>;

/**
 * Regressions a reviewer accepted, from E2E_A11Y_ACCEPT: comma-separated
 * `page:rule` pairs, e.g. `login:color-contrast`.
 */
export function acceptedRegressions(spec: string | undefined): Set<string> {
  const pairs = (spec ?? '')
    .split(',')
    .map(pair => pair.trim())
    .filter(pair => pair !== '');
  for (const pair of pairs) {
    if (!/^[^:\s]+:[^:\s]+$/.test(pair)) {
      throw new Error(`E2E_A11Y_ACCEPT takes page:rule pairs; got "${pair}"`);
    }
  }
  return new Set(pairs);
}

/**
 * The baseline entry an update run writes for one page. A rule may only lose
 * nodes; a new rule or a higher count keeps the old count and is refused,
 * unless its `page:rule` was accepted by name.
 */
export function nextBaseline(
  page: string,
  before: Counts,
  now: Counts,
  accepted: ReadonlySet<string>,
): { counts: Counts; refused: string[] } {
  const counts: Counts = {};
  const refused: string[] = [];
  const rules = [...new Set([...Object.keys(before), ...Object.keys(now)])].sort();
  for (const rule of rules) {
    const [was, is] = [before[rule] ?? 0, now[rule] ?? 0];
    let kept = is;
    if (is > was && !accepted.has(`${page}:${rule}`)) {
      refused.push(`${page}: ${rule} ${was} -> ${is}`);
      kept = was;
    }
    if (kept > 0) {
      counts[rule] = kept;
    }
  }
  return { counts, refused };
}
