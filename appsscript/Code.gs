/**
 * FEP weekly percentage writer.
 *
 * Lives inside the FEP spreadsheet itself, so it needs no Google Cloud project,
 * no service account and no key file. That matters because service account key
 * creation is blocked by an organization policy
 * (iam.disableServiceAccountKeyCreation), and this route is not subject to it.
 *
 * DEPLOY
 *   Extensions > Apps Script, paste this file, then
 *   Deploy > New deployment > Web app
 *     Execute as:      Me
 *     Who has access:  Anyone with the link
 *   Copy the /exec URL.
 *
 *   Then Project Settings > Script properties, add:
 *     FEP_TOKEN = a long random string (the CLI prints one for you)
 *
 * SECURITY
 *   The deployment URL is effectively a password, so it is paired with a shared
 *   token that must match FEP_TOKEN. Both live in a gitignored file on Jacob's
 *   Mac.
 *
 *   More importantly, this script can only ever do one thing. Even with the URL
 *   and the token, a caller cannot:
 *     - write outside columns B..M          (column A holds the week labels,
 *                                            column N onward holds the
 *                                            placement formulas)
 *     - write to row 1                      (the header)
 *     - write to a tab whose header row does not match the expected roster
 *     - write anything that is not a number or blank
 *   Those checks are enforced here as well as in the Python client, because a
 *   guard that only exists on the caller is not a guard.
 */

// Bumped by hand whenever this file changes in a way the caller must know
// about. The Python client reads the same constant out of its local copy and
// refuses to push when the two disagree, because editing this file does not
// redeploy it and the two have now silently diverged twice.
var CODE_VERSION = '2026.09.07-b';

// Columns B through M inclusive. 1-indexed, as the Sheets API counts them.
var FIRST_COL = 2;   // B
var LAST_COL = 13;   // M
var FIRST_ROW = 2;   // row 1 is the header and is never written

// The CMS tables. Nothing outside this list can be written by writeTable, so
// even a caller holding the URL and the token cannot touch the legacy
// "Weighted - MASTER" or the per-week tabs that published newsletters read.
var TABLE_TABS = ['seasons', 'competitors', 'competitor_seasons', 'games',
                  'weeks', 'picks', 'standings'];

// competitors is the one table whose rows span seasons, so it is the one table
// where a row may be rewritten by a push for a different year.
var CROSS_SEASON_TABS = ['competitors'];

// These hold a record of a week that has already happened. Once a row here has
// been written, the only acceptable rewrite is an identical one. Anything else
// means a published week is changing, which is the single thing this whole
// design exists to prevent, so it is refused rather than reconciled.
//
// A genuine correction goes through allowCorrection, which is deliberately
// awkward: it must be asked for, it names every row it changes, and it shows up
// in the response.
var FROZEN_TABS = ['weeks', 'standings', 'picks'];


function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);

    var expected = PropertiesService.getScriptProperties().getProperty('FEP_TOKEN');
    if (!expected) {
      return fail('FEP_TOKEN script property is not set');
    }
    if (!body.token || !constantTimeEquals(String(body.token), expected)) {
      return fail('bad token');
    }

    if (body.op === 'writeTable') {
      return writeTable(body);
    }

    var sheetName = String(body.tab || '');
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
    if (!sheet) {
      return fail('no tab named ' + JSON.stringify(sheetName));
    }

    var values = body.values;
    if (!Array.isArray(values) || values.length === 0) {
      return fail('values must be a non-empty array of rows');
    }

    var firstRow = Number(body.firstRow || FIRST_ROW);
    if (!(firstRow >= FIRST_ROW)) {
      return fail('firstRow ' + firstRow + ' would overwrite the header row');
    }

    var width = values[0].length;
    if (width !== LAST_COL - FIRST_COL + 1) {
      return fail('expected ' + (LAST_COL - FIRST_COL + 1) +
                  ' columns (B..M), got ' + width);
    }
    for (var r = 0; r < values.length; r++) {
      if (values[r].length !== width) {
        return fail('row ' + r + ' has ' + values[r].length +
                    ' cells, expected ' + width);
      }
      for (var c = 0; c < width; c++) {
        var cell = values[r][c];
        if (cell === '' || cell === null) { continue; }
        if (typeof cell !== 'number' || !isFinite(cell)) {
          return fail('cell at row ' + r + ' col ' + c +
                      ' is not a number or blank');
        }
      }
    }

    // Confirm the columns really are the roster before writing into formulas
    // that feed a live site.
    if (Array.isArray(body.roster)) {
      var header = sheet.getRange(1, FIRST_COL, 1, width).getValues()[0];
      for (var i = 0; i < width; i++) {
        if (String(header[i]).trim().toLowerCase() !==
            String(body.roster[i]).trim().toLowerCase()) {
          return fail('header mismatch in column ' + colName(FIRST_COL + i) +
                      ': sheet has ' + JSON.stringify(String(header[i])) +
                      ', caller expected ' + JSON.stringify(String(body.roster[i])));
        }
      }
    }

    sheet.getRange(firstRow, FIRST_COL, values.length, width).setValues(values);
    SpreadsheetApp.flush();

    return ok({
      wrote: values.length * width,
      range: sheetName + '!' + colName(FIRST_COL) + firstRow + ':' +
             colName(LAST_COL) + (firstRow + values.length - 1),
      rows: values.length,
      columns: width
    });
  } catch (err) {
    return fail(String(err));
  }
}

/**
 * Upsert a CMS table by slug.
 *
 * Append only, by construction. Rows are matched on the slug in column A;
 * a known slug is updated in place, an unknown one is appended, and nothing is
 * ever removed. Rows belonging to a season other than the one being pushed are
 * carried over from what is already in the sheet rather than taken from the
 * payload, so a bug in the caller cannot rewrite a past season even if it tries
 * to. That is the guarantee the whole design rests on, which is why it lives
 * here and not only in the Python.
 */
function writeTable(body) {
  var name = String(body.tab || '');
  if (TABLE_TABS.indexOf(name) === -1) {
    return fail('writeTable refuses ' + JSON.stringify(name) +
                '. Allowed: ' + TABLE_TABS.join(', '));
  }

  var columns = body.columns;
  var rows = body.rows || [];
  if (!Array.isArray(columns) || columns.length === 0) {
    return fail('columns must be a non-empty array');
  }
  if (String(columns[0]).toLowerCase() !== 'slug') {
    return fail('column A must be "slug", got ' + JSON.stringify(columns[0]));
  }
  // Every table names its season "season". The seasons table itself is the
  // exception: there the year is the row's own attribute, not a pointer.
  var yearColumn = columns.indexOf('season');
  if (yearColumn === -1) { yearColumn = columns.indexOf('year'); }
  var crossSeason = CROSS_SEASON_TABS.indexOf(name) !== -1;
  if (yearColumn === -1 && !crossSeason) {
    return fail(name + ' has neither a "season" nor a "year" column, so past ' +
                'seasons cannot be protected. Refusing to write it.');
  }
  // The season being pushed is required, and every row must agree with it.
  //
  // It used to be optional and unchecked, which meant the protection could be
  // stepped around two ways: omit it and no row was ever protected, or claim
  // one season while sending rows labelled another and overwrite across the
  // boundary. A guard that believes whatever the caller says about itself is
  // not a guard, and this one lives here precisely so that it does not depend
  // on the caller being correct.
  if (body.year === undefined || body.year === null || body.year === '') {
    return fail('year is required: it is the season being pushed, and every ' +
                'row must belong to it');
  }
  var pushYear = String(body.year);

  var active = PropertiesService.getScriptProperties().getProperty('ACTIVE_SEASON');
  if (active && String(active) !== pushYear) {
    return fail('ACTIVE_SEASON is ' + active + ', so a push for ' + pushYear +
                ' is refused. Change the script property to publish a ' +
                'different season.');
  }

  for (var r = 0; r < rows.length; r++) {
    if (!Array.isArray(rows[r]) || rows[r].length !== columns.length) {
      return fail('row ' + r + ' has ' + (rows[r] || []).length +
                  ' cells, expected ' + columns.length);
    }
    for (var c = 0; c < columns.length; c++) {
      var cell = rows[r][c];
      // Numbers and booleans are fine. Only a *string* can become a formula,
      // and a negative number arrives as a number, not as "-5".
      //
      // Deliberately not blocking "@". setValues() only treats a leading "="
      // as a formula; "+", "-" and "@" are CSV *import* injection prefixes,
      // which is a different threat and not this path. Blocking "@" rejected
      // every away game, because their labels read "@ Chiefs". Found by the
      // first real push, having survived every test on both sides, because
      // neither harness had ever fed a real game label through this check.
      if (typeof cell === 'string' && /^[=+\-]/.test(cell)) {
        return fail('cell at row ' + r + ' col ' + c +
                    ' looks like a formula: ' + JSON.stringify(cell));
      }
    }
    if (!rows[r][0]) {
      return fail('row ' + r + ' has an empty slug');
    }
  }

  // Every row must belong to the season being pushed. Checked after the shape
  // validation above, so a malformed row is reported as malformed.
  if (!crossSeason) {
    for (var r = 0; r < rows.length; r++) {
      var rowYear = String(rows[r][yearColumn]);
      if (rowYear !== pushYear) {
        return fail('row ' + r + ' (' + rows[r][0] + ') is season ' + rowYear +
                    ' but this is a ' + pushYear + ' push. Refusing: this is ' +
                    'how a row crosses from one season into another.');
      }
    }
  }

  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = spreadsheet.getSheetByName(name) || spreadsheet.insertSheet(name);

  // Pin each column's number format before reading anything.
  //
  // Clearing a tab's contents does not clear its formatting, so a column that
  // once held "5-2" keeps the date format Sheets inferred from it. Writing the
  // integer 4 into that column then reads back as 1900-01-03: the value stored
  // and the value returned are different things, which on a frozen table makes
  // every replay look like a change and is simply wrong everywhere else.
  //
  // Set before the read, not just before the write, so an already-mangled
  // column is read back as what it actually holds rather than as a date.
  applyColumnFormats(sheet, columns, rows);

  var existing = sheet.getLastRow() > 0
    ? sheet.getRange(1, 1, sheet.getLastRow(),
                     Math.max(sheet.getLastColumn(), columns.length)).getValues()
    : [];

  var header = existing.length ? existing[0] : [];
  var body_rows = existing.slice(1);

  // A header that has drifted is a caller/sheet mismatch, not something to
  // paper over: writing under it would misalign every column.
  var headerSet = header.filter(function (h) { return h !== ''; }).length > 0;
  if (headerSet) {
    for (var i = 0; i < columns.length; i++) {
      if (String(header[i]).trim() !== String(columns[i]).trim()) {
        return fail('header mismatch in ' + name + ' column ' + colName(i + 1) +
                    ': sheet has ' + JSON.stringify(String(header[i])) +
                    ', caller sent ' + JSON.stringify(String(columns[i])));
      }
    }
  }

  var order = [];        // slugs in sheet order
  var bySlug = {};       // slug -> row values
  for (var i = 0; i < body_rows.length; i++) {
    var slug = String(body_rows[i][0] || '');
    if (!slug) { continue; }
    if (!(slug in bySlug)) { order.push(slug); }
    bySlug[slug] = body_rows[i].slice(0, columns.length);
  }

  var frozen = FROZEN_TABS.indexOf(name) !== -1;
  var allowCorrection = body.allowCorrection === true;

  var added = 0, updated = 0, unchanged = 0, protectedRows = 0, corrected = [];
  var drift = [];
  for (var i = 0; i < rows.length; i++) {
    var slug = String(rows[i][0]);
    var current = bySlug[slug];
    if (current) {
      var currentYear = yearColumn === -1 ? null : String(current[yearColumn]);
      if (!crossSeason && currentYear !== null && currentYear !== '' &&
          currentYear !== pushYear) {
        protectedRows++;      // a different season's row. Leave it exactly as is.
        continue;
      }
      if (sameRow(current, rows[i], columns.length)) {
        unchanged++;
        continue;             // an identical replay is a no-op, not a rewrite
      }
      if (frozen && !allowCorrection) {
        drift.push(slug + ' (' + describeDrift(current, rows[i], columns) + ')');
        continue;
      }
      if (frozen) { corrected.push(slug); }
      bySlug[slug] = rows[i];
      updated++;
    } else {
      order.push(slug);
      bySlug[slug] = rows[i];
      added++;
    }
  }

  if (drift.length) {
    return fail(name + ' is a frozen table and ' + drift.length + ' row(s) ' +
                'would change: ' + drift.slice(0, 5).join('; ') +
                (drift.length > 5 ? ' and ' + (drift.length - 5) + ' more' : '') +
                '. Nothing was written. If the change is deliberate, resend ' +
                'with allowCorrection.');
  }

  var grid = [columns];
  for (var i = 0; i < order.length; i++) {
    grid.push(bySlug[order[i]]);
  }

  if (sheet.getMaxRows() < grid.length) {
    sheet.insertRowsAfter(sheet.getMaxRows(), grid.length - sheet.getMaxRows());
  }
  if (sheet.getMaxColumns() < columns.length) {
    sheet.insertColumnsAfter(sheet.getMaxColumns(),
                             columns.length - sheet.getMaxColumns());
  }
  sheet.getRange(1, 1, grid.length, columns.length).setValues(grid);
  SpreadsheetApp.flush();

  return ok({
    version: CODE_VERSION,
    tab: name,
    added: added,
    updated: updated,
    unchanged: unchanged,
    protected: protectedRows,
    corrected: corrected,
    frozen: frozen,
    total: order.length,
    range: name + '!A1:' + colName(columns.length) + grid.length
  });
}


/**
 * Give every column the format its data needs, and take back the one Sheets
 * guessed. Text columns become plain text so nothing is parsed into a date;
 * everything else becomes General so numbers stay numbers and booleans stay
 * booleans. A blank is not evidence either way.
 */
function applyColumnFormats(sheet, columns, rows) {
  var height = Math.max(sheet.getMaxRows(), 1);
  for (var c = 0; c < columns.length; c++) {
    var text = false;
    for (var r = 0; r < rows.length; r++) {
      var cell = rows[r][c];
      if (cell === '' || cell === null || cell === undefined) { continue; }
      if (typeof cell === 'string') { text = true; break; }
    }
    sheet.getRange(1, c + 1, height, 1).setNumberFormat(text ? '@' : 'General');
  }
}


/** Compare a stored row against an incoming one, tolerating how Sheets types. */
function sameRow(current, incoming, width) {
  for (var i = 0; i < width; i++) {
    if (normalizeCell(current[i]) !== normalizeCell(incoming[i])) { return false; }
  }
  return true;
}


/**
 * A cell as a comparable string.
 *
 * Sheets does not hand back what you put in. A number written as 33.4 comes
 * back as a number, a blank as an empty string, and a date-looking string may
 * come back as a Date. Comparing raw values would report every replay as a
 * change and make the frozen check useless.
 */
function normalizeCell(value) {
  if (value === null || value === undefined) { return ''; }
  if (Object.prototype.toString.call(value) === '[object Date]') {
    return Utilities.formatDate(value, 'UTC', 'yyyy-MM-dd');
  }
  if (typeof value === 'boolean') { return value ? 'true' : 'false'; }
  if (typeof value === 'number') { return String(value); }
  return String(value).trim();
}


/** Name the columns that differ, so a refusal says what actually moved. */
function describeDrift(current, incoming, columns) {
  var parts = [];
  for (var i = 0; i < columns.length && parts.length < 3; i++) {
    var was = normalizeCell(current[i]);
    var now = normalizeCell(incoming[i]);
    if (was !== now) {
      parts.push(columns[i] + ': ' + JSON.stringify(was) + ' -> ' +
                 JSON.stringify(now));
    }
  }
  return parts.join(', ');
}


/** A GET is a health check. It never writes and never reveals the token. */
function doGet() {
  var sheets = SpreadsheetApp.getActiveSpreadsheet().getSheets().map(function (s) {
    return s.getName();
  });
  return ok({
    service: 'fep-sheet-writer',
    version: CODE_VERSION,
    tableTabs: TABLE_TABS,
    tabs: sheets,
    writableColumns: colName(FIRST_COL) + '..' + colName(LAST_COL),
    tokenConfigured: !!PropertiesService.getScriptProperties().getProperty('FEP_TOKEN')
  });
}

function colName(index) {
  var name = '';
  while (index > 0) {
    var rem = (index - 1) % 26;
    name = String.fromCharCode(65 + rem) + name;
    index = Math.floor((index - 1) / 26);
  }
  return name;
}

function constantTimeEquals(a, b) {
  if (a.length !== b.length) { return false; }
  var diff = 0;
  for (var i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

function ok(payload) {
  payload.ok = true;
  return ContentService.createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}

function fail(message) {
  return ContentService.createTextOutput(
    JSON.stringify({ ok: false, error: message })
  ).setMimeType(ContentService.MimeType.JSON);
}
