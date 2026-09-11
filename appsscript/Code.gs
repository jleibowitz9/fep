/**
 * FEP CMS table writer.
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
 *   More importantly, this script can only ever do one thing: upsert one of
 *   the seven CMS tables, by slug. Even with the URL and the token, a caller
 *   cannot:
 *     - write to a tab outside TABLE_TABS
 *     - write a row that belongs to another season
 *     - move a row in a frozen table without saying so (allowCorrection)
 *     - write a cell that could be read as a formula
 *     - write under a header that does not match the columns it sent. A
 *       caller may APPEND columns (blank header cells at the end take the
 *       new names); it may not rename, reorder, or drop one.
 *   Those checks are enforced here as well as in the Python client, because a
 *   guard that only exists on the caller is not a guard.
 *
 *   Until September 2026 this file also carried a second op: raw numbers into
 *   B2:M20 of the legacy `Weighted - MASTER` tab, which fed the standings on
 *   the site before the `standings` table did. Nothing reads that tab any more
 *   and the Python writer was removed with it. The op lingered here so that
 *   removing dead code would not force a redeploy on its own; this version
 *   needed one anyway, so it is gone. A request for it is now refused, which
 *   closes the one path that could still write numbers into any tab.
 */

// Bumped by hand whenever this file changes in a way the caller must know
// about. The Python client reads the same constant out of its local copy and
// refuses to push when the two disagree, because editing this file does not
// redeploy it and the two have now silently diverged twice.
var CODE_VERSION = '2026.09.11-a';

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

// A frozen table may still hold one column that fills in. `picks.correct` is a
// game's result seen from the pick's side, and a result genuinely becomes known
// during the season, so that cell moves from blank to TRUE or FALSE exactly
// once. Listing it here buys precisely that and nothing else: the fill is
// allowed only when the sheet's cell is blank and the incoming one is not. A
// cell that already holds an answer and is now sent a different one is drift
// and is still refused, as is any movement in any column not named here. The
// alternative was to drop `picks` out of FROZEN_TABS entirely, which would have
// left `pick` itself unguarded to buy one column.
var FILLABLE_COLUMNS = {
  picks: ['correct'],
  // The Decision Tree columns appended to `weeks` in September 2026. Every
  // published week already had these numbers in its snapshot, so the rows
  // fill in once from blank. Necessary rather than convenient: a push is per
  // season, and the first season's push writes '' into every OTHER season's
  // new cells (rows are carried over at the new width), so by the time that
  // season pushes, the columns are no longer newly appended. After the fill,
  // a different value or a value going back to blank is drift like anywhere.
  weeks: ['decided_tb1', 'decided_tb2', 'decided_tb3', 'decided_split',
          'decided_outright_change', 'decided_tb1_change',
          'decided_tb2_change', 'decided_tb3_change']
};


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

    if (body.op !== 'writeTable') {
      return fail('unknown op ' + JSON.stringify(body.op === undefined ? null : body.op) +
                  '. This deployment writes the CMS tables and nothing else.');
    }
    return writeTable(body);
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

  // Widen the sheet BEFORE anything reads it. getRange throws on a range past
  // getMaxColumns(), a fresh tab has 26, and `weeks` is exactly 26 wide now.
  // This used to sit just before the write, after two reads at the new width.
  if (sheet.getMaxColumns() < columns.length) {
    sheet.insertColumnsAfter(sheet.getMaxColumns(),
                             columns.length - sheet.getMaxColumns());
  }

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
      var have = normalizeCell(header[i]);
      if (have === String(columns[i]).trim()) { continue; }
      // A pure append is not drift: the sheet's header ends here and every
      // cell from this one on is blank, so the caller is adding columns. The
      // grid write below lays the new names down. A blank followed by a named
      // cell is a hole, and a named cell that differs is a rename or a
      // reorder; both still refuse, because writing under either would
      // misalign every column after it.
      var appending = have === '';
      for (var j = i; appending && j < header.length; j++) {
        if (normalizeCell(header[j]) !== '') { appending = false; }
      }
      if (appending) { break; }
      return fail('header mismatch in ' + name + ' column ' + colName(i + 1) +
                  ': sheet has ' + JSON.stringify(String(header[i])) +
                  ', caller sent ' + JSON.stringify(String(columns[i])));
    }
    // The sheet may not be wider than the caller. Those columns used to be
    // dropped from every comparison and left behind by the write, so a caller
    // that stopped sending a column silently stopped guarding it.
    for (var k = columns.length; k < header.length; k++) {
      if (normalizeCell(header[k]) !== '') {
        return fail('the ' + name + ' sheet has a column the caller did not ' +
                    'send: ' + colName(k + 1) + ' ' + JSON.stringify(String(header[k])) +
                    '. Columns are appended, never dropped; refusing.');
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
  var fillable = fillableIndices(name, columns);

  var added = 0, updated = 0, unchanged = 0, protectedRows = 0, corrected = [];
  var filled = 0;
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
      if (frozen && isOnlyFilling(current, rows[i], columns.length, fillable)) {
        // Blank becoming known. Not a rewrite, so it needs no correction flag.
        bySlug[slug] = rows[i];
        filled++;
        updated++;
        continue;
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
    filled: filled,
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


/** Indices of the columns a frozen table is allowed to fill in later. */
function fillableIndices(name, columns) {
  var names = FILLABLE_COLUMNS[name] || [];
  var indices = {};
  for (var i = 0; i < columns.length; i++) {
    if (names.indexOf(String(columns[i]).trim()) !== -1) { indices[i] = true; }
  }
  return indices;
}


/**
 * True when the only difference is a fillable cell going from blank to a value.
 *
 * Deliberately one-directional. A value going back to blank is a row losing
 * something it had published, and a value changing to a different value is the
 * exact rewrite the frozen check exists to catch; both fall through to drift.
 */
function isOnlyFilling(current, incoming, width, fillable) {
  var anyFill = false;
  for (var i = 0; i < width; i++) {
    var was = normalizeCell(current[i]);
    var now = normalizeCell(incoming[i]);
    if (was === now) { continue; }
    if (!fillable[i] || was !== '' || now === '') { return false; }
    anyFill = true;
  }
  return anyFill;
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


/**
 * A GET is a health check. It never writes and never reveals the token.
 *
 * It also no longer lists the spreadsheet's tabs. The deployment is reachable
 * by anyone holding its URL, and the health check needs exactly two facts to
 * answer "is this checkout what Google is running": the version and whether a
 * token is configured. Everything else it used to say was about the sheet,
 * not about the deployment, and was more than a URL-holder needs to know.
 */
function doGet() {
  return ok({
    service: 'fep-sheet-writer',
    version: CODE_VERSION,
    tableTabs: TABLE_TABS,
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
