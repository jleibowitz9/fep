/**
 * One-time: turn the derived per-week tabs into permanent values.
 *
 * WHY
 *   Each "Weighted - W7" tab is a live formula reading "Weighted - MASTER".
 *   That means it shows whatever season MASTER currently holds, not the season
 *   the newsletter was written about. Pushing 2026 into MASTER would silently
 *   rewrite every historical newsletter's standings.
 *
 *   Replacing those formulas with their current values makes each week tab a
 *   photograph. The tab keeps its id, so every Framer collection and every
 *   component mapping keeps working exactly as it does now. Nothing in Framer
 *   is touched. The only thing that changes is that the numbers stop moving.
 *
 * HOW TO RUN
 *   1. File > Make a copy, so there is an undo that does not depend on me.
 *   2. Extensions > Apps Script, add this file alongside Code.gs.
 *   3. Run previewFreeze() first. Read the log. It writes nothing.
 *   4. Run freezeWeekTabs() when the log looks right.
 *
 * SCOPE
 *   Only tabs named exactly "Weighted - W<number>" or "Straight - W<number>".
 *   MASTER is never touched, and neither is any tab that does not match.
 *   This is deliberately not reachable from the web app: the deployment stays
 *   able to do one thing, which is write B2:M20.
 */

var WEEK_TAB = /^(Weighted|Straight) - W(\d+)$/;

function previewFreeze() {
  _freeze(true);
}

function freezeWeekTabs() {
  _freeze(false);
}

function _freeze(preview) {
  var sheets = SpreadsheetApp.getActiveSpreadsheet().getSheets();
  var touched = 0, skipped = [], totalFormulas = 0;

  Logger.log(preview ? 'PREVIEW, nothing will be written' : 'FREEZING');

  for (var i = 0; i < sheets.length; i++) {
    var sheet = sheets[i];
    var name = sheet.getName();
    if (!WEEK_TAB.test(name)) {
      skipped.push(name);
      continue;
    }

    var range = sheet.getDataRange();
    var formulas = range.getFormulas();
    var count = 0;
    for (var r = 0; r < formulas.length; r++) {
      for (var c = 0; c < formulas[r].length; c++) {
        if (formulas[r][c] !== '') { count++; }
      }
    }
    totalFormulas += count;

    if (count === 0) {
      Logger.log('  %s: already values (%s cells), nothing to do',
                 name, range.getNumRows() * range.getNumColumns());
      continue;
    }

    if (!preview) {
      // Reading the values and writing them back is what collapses a formula
      // to its result. Number formats are not part of setValues, so they
      // survive untouched.
      range.setValues(range.getValues());
    }
    touched++;
    Logger.log('  %s: %s formula cells in %s', name, count, range.getA1Notation());
  }

  if (!preview) { SpreadsheetApp.flush(); }

  Logger.log('');
  Logger.log('%s tab(s) with formulas, %s formula cells total.',
             touched, totalFormulas);
  Logger.log('Left alone: %s', skipped.join(', '));
  if (preview) {
    Logger.log('');
    Logger.log('Nothing was written. Run freezeWeekTabs() to apply.');
  }
}
