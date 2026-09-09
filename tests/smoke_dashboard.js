/*
 * Load a built dashboard's JavaScript and report anything it throws.
 *
 *     node tests/smoke_dashboard.js path/to/index.html
 *
 * WHY NOT A REAL BROWSER
 * ----------------------
 * The bug this exists to catch was a load-time TypeError: with no games
 * played, `played[played.length-1].result` threw and the page rendered a
 * sidebar and nothing else. Catching that needs the page's own code to run
 * against the page's own data -- it does not need layout, paint or a network
 * stack. So this runs the script against a DOM stub instead of pulling in
 * Playwright and a browser binary.
 *
 * What it does NOT check: CSS, layout, focus order, or anything that depends
 * on real rendering. Those still want a browser. This is the cheap half that
 * covers the expensive failure.
 *
 * Exits 0 with "OK" on success, 1 with the error on failure.
 */

'use strict';

const fs = require('fs');
const vm = require('vm');

const file = process.argv[2];
if (!file) {
    console.error('usage: node tests/smoke_dashboard.js <built.html>');
    process.exit(2);
}
const html = fs.readFileSync(file, 'utf8');

// ---------------------------------------------------------------------------
// A DOM small enough to fit on a screen and large enough to run the template.
// ---------------------------------------------------------------------------

function makeNode(tag, id) {
    const node = {
        tagName: (tag || 'div').toUpperCase(),
        id: id || '',
        dataset: {},
        style: {},
        children: [],
        hidden: false,
        _html: '',
        _text: '',
        _classes: new Set(),
        _handlers: {},
    };
    node.classList = {
        add: (...c) => c.forEach(x => node._classes.add(x)),
        remove: (...c) => c.forEach(x => node._classes.delete(x)),
        toggle: (c, on) => (on === undefined
            ? (node._classes.has(c) ? node._classes.delete(c) : node._classes.add(c))
            : (on ? node._classes.add(c) : node._classes.delete(c))),
        contains: c => node._classes.has(c),
    };
    Object.defineProperty(node, 'className', {
        get: () => [...node._classes].join(' '),
        set: v => { node._classes = new Set(String(v).split(/\s+/).filter(Boolean)); },
    });
    Object.defineProperty(node, 'innerHTML', {
        get: () => node._html,
        // Recording the markup is the point: a template literal that
        // dereferences undefined throws before it ever gets here.
        set: v => { node._html = String(v); },
    });
    Object.defineProperty(node, 'textContent', {
        get: () => node._text,
        set: v => { node._text = String(v); },
    });
    node.setAttribute = (k, v) => { node[k] = String(v); };
    node.getAttribute = k => (k in node ? String(node[k]) : null);
    node.removeAttribute = k => { delete node[k]; };
    node.appendChild = c => { node.children.push(c); return c; };
    node.replaceChild = () => {};
    node.addEventListener = (t, fn) => { (node._handlers[t] = node._handlers[t] || []).push(fn); };
    node.removeEventListener = () => {};
    node.querySelector = () => null;
    node.querySelectorAll = () => [];
    node.closest = () => null;
    node.matches = () => false;
    node.focus = () => { doc.activeElement = node; };
    node.click = () => { if (node.onclick) node.onclick({ target: node }); };
    node.getBoundingClientRect = () => ({ top: 0, left: 0, width: 0, height: 0 });
    node.contains = () => false;
    return node;
}

const nodes = new Map();
function byId(id) {
    if (!nodes.has(id)) nodes.set(id, makeNode('div', id));
    return nodes.get(id);
}

// The data block is a real element whose textContent the page parses.
const dataMatch = html.match(
    /<script type="application\/json" id="data">([\s\S]*?)<\/script>/);
if (!dataMatch) {
    console.error('FAIL: no <script type="application/json" id="data"> block');
    process.exit(1);
}
byId('data').textContent = dataMatch[1];

const doc = {
    activeElement: null,
    getElementById: byId,
    createElement: makeNode,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    body: makeNode('body'),
    documentElement: makeNode('html'),
};
doc.body.addEventListener = () => {};

const sandbox = {
    document: doc,
    console,
    JSON,
    Math,
    Object,
    Array,
    String,
    Number,
    Boolean,
    Set,
    Map,
    Date,
    RegExp,
    Error,
    isNaN,
    parseInt,
    parseFloat,
    setTimeout: () => 0,
    clearTimeout: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    getComputedStyle: () => ({}),
    navigator: { clipboard: { writeText: () => Promise.resolve() } },
    Image: function () { this.onload = null; this.onerror = null; },
    location: { href: '' },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

// ---------------------------------------------------------------------------
// Run every executable inline script, in order, as the browser would.
// ---------------------------------------------------------------------------

const scripts = [];
const re = /<script([^>]*)>([\s\S]*?)<\/script>/g;
let m;
while ((m = re.exec(html)) !== null) {
    const attrs = m[1] || '';
    if (/type\s*=\s*"application\/json"/.test(attrs)) continue;  // data block
    if (/\bsrc\s*=/.test(attrs)) continue;                       // none today
    scripts.push(m[2]);
}
if (!scripts.length) {
    console.error('FAIL: the page has no executable script');
    process.exit(1);
}

const context = vm.createContext(sandbox);
try {
    scripts.forEach((code, i) => {
        vm.runInContext(code, context, { filename: `inline-${i}.js`, timeout: 20000 });
    });
} catch (err) {
    console.error('FAIL: the page threw while initialising');
    console.error('  ' + (err && err.stack ? err.stack.split('\n')[0] : err));
    if (err && err.stack) {
        const where = err.stack.split('\n').find(l => l.includes('inline-'));
        if (where) console.error('  at ' + where.trim());
    }
    process.exit(1);
}

// A page that runs but renders nothing is the failure we actually saw.
const views = ['v-board', 'v-story', 'v-picks', 'v-whatif', 'v-chart', 'v-run'];
const empty = views.filter(v => !byId(v).innerHTML.trim());
if (empty.length) {
    console.error('FAIL: these views rendered no markup: ' + empty.join(', '));
    process.exit(1);
}

console.log('OK: ' + scripts.length + ' script block(s) ran, ' +
            views.length + ' views rendered');
