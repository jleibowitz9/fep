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
  this.insertColumnsAfter = () => {};
  this.getRange = (r,c,nr,nc) => ({
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
global.PropertiesService = { getScriptProperties: () => ({ getProperty: () => 'secret' }) };
global.ContentService = {
  MimeType: { JSON: 'json' },
  createTextOutput: t => ({ setMimeType: () => JSON.parse(t) }),
};
global.Logger = { log: () => {} };
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
check('appends a new week, updates the old rows', r.ok && r.added===1 && r.updated===2, r);

console.log('\n--- the guarantee: a past season cannot be rewritten ---');
r = post({op:'writeTable', tab:'standings', year:2027, columns:COLS,
          rows:[row(2027,1,'amir',9)]});
check('2027 appends alongside 2026', r.ok && r.added===1 && r.total===4, r);

// A caller that tries to overwrite a 2026 row while pushing 2027.
r = post({op:'writeTable', tab:'standings', year:2027, columns:COLS,
          rows:[['2026-w01-amir', 2026, 1, 'amir', 99999]]});
check('refuses to touch a 2026 row during a 2027 push', r.ok && r.protected===1 && r.updated===0, r);
const grid = SHEETS['standings'].grid;
const amir = grid.find(x => x[0] === '2026-w01-amir');
check('the 2026 value is still 10, not 99999', amir && amir[4] === 10, amir);

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

console.log('\n--- nothing is ever deleted ---');
const before = SHEETS['standings'].grid.length;
r = post({op:'writeTable', tab:'standings', year:2026, columns:COLS, rows:[row(2026,1,'amir',11)]});
check('a one-row push does not truncate the table',
      r.ok && SHEETS['standings'].grid.length === before, {before, after: SHEETS['standings'].grid.length});

console.log(`\n${pass} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
