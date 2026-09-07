// Guard tests for Code.gs, run with:  node appsscript/test_code.js
//
// These cover the server side of the contract, which the Python tests
// cannot reach: the tab allowlist, formula rejection, header drift, and
// above all that a push for one season cannot rewrite another season's
// rows even when it explicitly tries to.
// Minimal Apps Script stand-in, enough to exercise writeTable's guards.
const fs = require('fs');
function FakeSheet(name, grid) {
  this.name = name; this.grid = grid || [];
  this.getName = () => this.name;
  this.getLastRow = () => this.grid.length;
  this.getLastColumn = () => this.grid.reduce((m,r)=>Math.max(m,r.length),0);
  this.getMaxRows = () => Math.max(this.grid.length, 1000);
  this.getMaxColumns = () => 40;
  this.insertRowsAfter = () => {};
  this.formats = {};
  this.insertColumnsAfter = () => {};
  this.getRange = (r,c,nr,nc) => ({
    setNumberFormat: (f) => { for(let j=0;j<nc;j++) this.formats[c-1+j]=f; },
    getValues: () => {
      const out=[];
      for(let i=0;i<nr;i++){const row=this.grid[r-1+i]||[];const cells=[];
        for(let j=0;j<nc;j++) cells.push(row[c-1+j]===undefined?'':row[c-1+j]);
        out.push(cells);} return out;
    },
    setValues: (v) => { for(let i=0;i<v.length;i++) this.grid[r-1+i]=v[i].slice();
                        this.grid.length = r-1+v.length; },
    getA1Notation: () => 'A1'
  });
}
const SHEETS = {};
global.SpreadsheetApp = {
  getActiveSpreadsheet: () => ({
    getSheetByName: n => SHEETS[n] || null,
    insertSheet: n => (SHEETS[n] = new FakeSheet(n, [])),
    getSheets: () => Object.values(SHEETS),
  }),
  flush: () => {},
};
const PROPS = { FEP_TOKEN: 'secret' };   // ACTIVE_SEASON deliberately unset
global.PropertiesService = {
  getScriptProperties: () => ({ getProperty: (k) => PROPS[k] || null }),
};
global.ContentService = {
  MimeType: { JSON: 'json' },
  createTextOutput: t => ({ setMimeType: () => JSON.parse(t) }),
};
global.Logger = { log: () => {} };
global.Utilities = {
  formatDate: (d) => d.toISOString().slice(0, 10),
};
// Apps Script has no modules, so the file is evaluated as-is. Node will not
// load a .gs extension, hence the read-and-eval.
eval(fs.readFileSync(require('path').join(__dirname, 'Code.gs'), 'utf8'));

const post = b => doPost({ postData: { contents: JSON.stringify(Object.assign({token:'secret'}, b)) } });
let pass = 0, failed = 0;
const check = (label, cond, detail) => {
  if (cond) { pass++; console.log('  ok    ' + label); }
  else { failed++; console.log('  FAIL  ' + label + (detail ? '  ' + JSON.stringify(detail) : '')); }
};

const COLS = ['slug','season','week','name','weighted'];
const row = (y,w,n,v) => [`${y}-w${String(w).padStart(2,'0')}-${n}`, y, w, n, v];

console.log('\n--- writeTable ---');
let r = post({op:'writeTable', tab:'standings', year:2026, columns:COLS,
              rows:[row(2026,1,'amir',10), row(2026,1,'pop',12)]});
check('creates the tab and writes both rows', r.ok && r.added===2 && r.total===2, r);

r = post({op:'writeTable', tab:'standings', year:2026, columns:COLS,
          rows:[row(2026,1,'amir',10), row(2026,1,'pop',12), row(2026,2,'amir',14)]});
check('appends a new week, replays the old rows as no-ops',
      r.ok && r.added===1 && r.unchanged===2 && r.updated===0, r);

console.log('\n--- a frozen row cannot be quietly rewritten ---');
r = post({op:'writeTable', tab:'standings', year:2026, columns:COLS,
          rows:[row(2026,1,'amir',99)]});
check('refuses to change an already published row',
      !r.ok && /frozen table/.test(r.error), r);
check('and says which column moved', !r.ok && /weighted/.test(r.error), r);
check('the stored value is untouched',
      SHEETS['standings'].grid.find(x=>x[0]==='2026-w01-amir')[4] === 10);
r = post({op:'writeTable', tab:'standings', year:2026, columns:COLS,
          rows:[row(2026,1,'amir',99)], allowCorrection:true});
check('allowCorrection lets a deliberate correction through',
      r.ok && r.updated===1 && r.corrected.length===1, r);
post({op:'writeTable', tab:'standings', year:2026, columns:COLS,
      rows:[row(2026,1,'amir',10)], allowCorrection:true});   // put it back
r = post({op:'writeTable', tab:'seasons', year:2026,
          columns:['slug','season','status'], rows:[['2026',2026,'final']]});
check('a live table still updates freely', r.ok, r);
r = post({op:'writeTable', tab:'seasons', year:2026,
          columns:['slug','season','status'], rows:[['2026',2026,'in_progress']]});
check('and updates again without complaint', r.ok && r.updated===1, r);

console.log('\n--- the guarantee: a past season cannot be rewritten ---');
r = post({op:'writeTable', tab:'standings', year:2027, columns:COLS,
          rows:[row(2027,1,'amir',9)]});
check('2027 appends alongside 2026', r.ok && r.added===1 && r.total===4, r);

// A caller that tries to overwrite a 2026 row while pushing 2027. This is now
// caught by the consistency rule before it ever reaches the protection pass,
// which is a better outcome: the whole write is refused rather than one row
// being quietly skipped.
r = post({op:'writeTable', tab:'standings', year:2027, columns:COLS,
          rows:[['2026-w01-amir', 2026, 1, 'amir', 99999]]});
check('refuses the whole write when a row belongs to another season',
      !r.ok && /crosses from one season/.test(r.error), r);
const amir0 = SHEETS['standings'].grid.find(x => x[0] === '2026-w01-amir');
check('the 2026 value is still 10, not 99999', amir0 && amir0[4] === 10, amir0);

// Defence in depth: an honestly-labelled row whose slug already belongs to a
// different season in the sheet. Only reachable if the sheet is already
// inconsistent, which is exactly when a last line of defence earns its keep.
SHEETS['standings'].grid.push(['2027-w09-ghost', 2026, 9, 'ghost', 42]);
r = post({op:'writeTable', tab:'standings', year:2027, columns:COLS,
          rows:[['2027-w09-ghost', 2027, 9, 'ghost', 1]]});
check('leaves a row the sheet says belongs to another season',
      r.ok && r.protected===1 && r.updated===0, r);
check('and its value is untouched',
      SHEETS['standings'].grid.find(x => x[0] === '2027-w09-ghost')[4] === 42);

console.log('\n--- the guard does not believe the caller ---');
// Both of these were reproducible bypasses before the season became required
// and every row had to agree with it.
r = post({op:'writeTable', tab:'standings', columns:COLS,
          rows:[row(2026,1,'amir',77)]});
check('refuses a push with no season at all', !r.ok && /year is required/.test(r.error), r);
r = post({op:'writeTable', tab:'standings', year:2026, columns:COLS,
          rows:[['2026-w01-amir', 2027, 1, 'amir', 77]]});
check('refuses a row whose season disagrees with the push',
      !r.ok && /crosses from one season/.test(r.error), r);
check('neither bypass moved the stored value',
      SHEETS['standings'].grid.find(x=>x[0]==='2026-w01-amir')[4] === 10);

console.log('\n--- the other guards ---');
r = post({op:'writeTable', tab:'Weighted - MASTER', year:2026, columns:COLS, rows:[row(2026,1,'a',1)]});
check('refuses a tab outside the allowlist', !r.ok && /refuses/.test(r.error), r);
r = post({op:'writeTable', tab:'Weighted - W7', year:2026, columns:COLS, rows:[row(2026,1,'a',1)]});
check('refuses a legacy per-week tab', !r.ok, r);
r = post({op:'writeTable', tab:'standings', year:2026, columns:COLS,
          rows:[['2026-w03-x', 2026, 3, '=IMPORTRANGE("evil")', 1]]});
check('refuses a formula string', !r.ok && /formula/.test(r.error), r);
r = post({op:'writeTable', tab:'standings', year:2026, columns:COLS,
          rows:[['2026-w03-y', 2026, 3, 'y', -4.2]]});
check('allows a negative NUMBER', r.ok, r);
// Real data, not synthetic. Every away game's label starts with "@".
r = post({op:'writeTable', tab:'games', year:2026,
          columns:['slug','season','label','opponent','home_away'],
          rows:[['2026-w02-chiefs', 2026, '@ Chiefs', 'Chiefs', 'away'],
                ['2026-w01-cowboys', 2026, 'vs. Cowboys', 'Cowboys', 'home'],
                ['2026-w05-jaguars', 2026, 'vs. Jaguars (London)', 'Jaguars', 'home']]});
check('allows real game labels, including "@ Chiefs"', r.ok && r.added===3, r);
r = post({op:'writeTable', tab:'games', year:2026,
          columns:['slug','season','label','opponent','home_away'],
          rows:[['2026-w09-x', 2026, '=IMPORTRANGE("evil")', 'x', 'home']]});
check('still refuses a leading "="', !r.ok && /formula/.test(r.error), r);
r = post({op:'writeTable', tab:'games', year:2026,
          columns:['slug','season','label','opponent','home_away'],
          rows:[['2026-w09-y', 2026, '-1+1', 'y', 'home']]});
check('still refuses a leading "-"', !r.ok && /formula/.test(r.error), r);
r = post({op:'writeTable', tab:'standings', year:2026, columns:['name','year'], rows:[['a',2026]]});
check('refuses when column A is not slug', !r.ok && /slug/.test(r.error), r);
r = post({op:'writeTable', tab:'games', year:2026, columns:['slug','week'], rows:[['2026-w1',1]]});
check('refuses a table with no season column at all', !r.ok && /season/.test(r.error), r);
r = post({op:'writeTable', tab:'standings', year:2026,
          columns:['slug','season','week','name','WEIGHTED'], rows:[row(2026,9,'z',1)]});
check('refuses a drifted header', !r.ok && /header mismatch/.test(r.error), r);
r = post({op:'writeTable', tab:'standings', year:2026, columns:COLS, rows:[['',2026,1,'a',1]]});
check('refuses an empty slug', !r.ok && /empty slug/.test(r.error), r);
r = post({op:'writeTable', tab:'standings', year:2026, columns:COLS, rows:[['2026-w1-a',2026,1]]});
check('refuses a short row', !r.ok && /cells/.test(r.error), r);
r = doPost({postData:{contents:JSON.stringify({token:'wrong',op:'writeTable',tab:'standings',columns:COLS,rows:[]})}});
check('refuses a bad token', !r.ok && /bad token/.test(r.error), r);

console.log('\n--- ACTIVE_SEASON, a lock only the sheet owner can set ---');
PROPS.ACTIVE_SEASON = '2026';
r = post({op:'writeTable', tab:'standings', year:2026, columns:COLS,
          rows:[row(2026,4,'amir',5)]});
check('allows the active season', r.ok, r);
r = post({op:'writeTable', tab:'standings', year:2027, columns:COLS,
          rows:[row(2027,1,'amir',5)]});
check('refuses any other season', !r.ok && /ACTIVE_SEASON is 2026/.test(r.error), r);
delete PROPS.ACTIVE_SEASON;
r = post({op:'writeTable', tab:'standings', year:2027, columns:COLS,
          rows:[row(2027,3,'amir',5)]});
check('unset means no extra restriction', r.ok && r.added===1, r);

console.log('\n--- column formats, so Sheets stops guessing ---');
delete SHEETS['fmt'];
SHEETS['fmt'] = undefined; delete SHEETS['fmt'];
r = post({op:'writeTable', tab:'weeks', year:2026,
          columns:['slug','season','label','wins','losses','is_bye'],
          rows:[['2026-w01', 2026, 'Week 1', 4, 1, false],
                ['2026-w02', 2026, 'Week 2', 5, 1, true]]});
check('writes', r.ok, r);
const F = SHEETS['weeks'].formats;
check('a text column is pinned to plain text', F[0]==='@' && F[2]==='@', F);
check('a number column is left General', F[3]==='General' && F[4]==='General', F);
check('a boolean column is left General', F[5]==='General', F);
check('the season column is General, not text', F[1]==='General', F);

console.log('\n--- nothing is ever deleted ---');
const before = SHEETS['standings'].grid.length;
r = post({op:'writeTable', tab:'standings', year:2026, columns:COLS, rows:[row(2026,1,'amir',10)]});
check('a one-row replay does not truncate the table',
      r.ok && r.unchanged===1 && SHEETS['standings'].grid.length === before,
      {before, after: SHEETS['standings'].grid.length});

console.log(`\n${pass} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
