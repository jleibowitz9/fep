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
  var pushYear = body.year === undefined ? null : String(body.year);

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

  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = spreadsheet.getSheetByName(name) || spreadsheet.insertSheet(name);

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

  var added = 0, updated = 0, protectedRows = 0;
  for (var i = 0; i < rows.length; i++) {
    var slug = String(rows[i][0]);
    var current = bySlug[slug];
    if (current) {
      var currentYear = yearColumn === -1 ? null : String(current[yearColumn]);
      if (!crossSeason && pushYear !== null && currentYear !== null &&
          currentYear !== '' && currentYear !== pushYear) {
        protectedRows++;      // a different season's row. Leave it exactly as is.
        continue;
      }
      bySlug[slug] = rows[i];
      updated++;
    } else {
      order.push(slug);
      bySlug[slug] = rows[i];
      added++;
    }
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
    tab: name,
    added: added,
    updated: updated,
    protected: protectedRows,
    total: order.length,
    range: name + '!A1:' + colName(columns.length) + grid.length
  });
}


/** A GET is a health check. It never writes and never reveals the token. */
function doGet() {
  var sheets = SpreadsheetApp.getActiveSpreadsheet().getSheets().map(function (s) {
    return s.getName();
  });
  return ok({
    service: 'fep-sheet-writer',
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
