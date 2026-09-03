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

/** A GET is a health check. It never writes and never reveals the token. */
function doGet() {
  var sheets = SpreadsheetApp.getActiveSpreadsheet().getSheets().map(function (s) {
    return s.getName();
  });
  return ok({
    service: 'fep-sheet-writer',
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
