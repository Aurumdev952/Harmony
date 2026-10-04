'''The JavaScript epi week extraction WP-8a removed from the query builder
(db/druid/js_formulas/week_extraction.py before c808afa), kept verbatim so
`run_audit.py parity --js` can compare it with the native one on a Druid that
still runs JavaScript. Harmony never sends it.
'''
WHO_EPI_WEEK_EXTRACTION_FORMULA = '''
function epiWeekOfYear(time) {
  /* Calculate WHO epi year start for a year. */
  function calculateEpiYearStart(year) {
    var epiYearStart = new Date(year, 0, 4);
    var dayOfWeek = epiYearStart.getDay();
    var offset = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
    epiYearStart.setDate(4 - offset);
    return epiYearStart;
  }

  var input = new Date(time);
  var inputYear = input.getFullYear();
  var epiYearStart = calculateEpiYearStart(inputYear);
  /*
   * If this date falls between Dec 29 and Dec 31, it is possible for it to be in a
   * different epi year than its calendar year.
   */
  if (input.getMonth() === 11 && input.getDate() >= 29) {
    var nextEpiYearStart = calculateEpiYearStart(inputYear + 1);
    if (input >= nextEpiYearStart) {
      epiYearStart = nextEpiYearStart;
    }
  }

  var daysSinceStart = (input - epiYearStart) / (1000 * 60 * 60 * 24);
  var epiWeek = Math.floor(daysSinceStart / 7);
  /* Epi year start for year 3000. */
  var outputEpiYearStart = new Date(3000, 0, -1);
  outputEpiYearStart.setDate(outputEpiYearStart.getDate() + 7 * epiWeek);
  return outputEpiYearStart.toISOString();
}
'''
