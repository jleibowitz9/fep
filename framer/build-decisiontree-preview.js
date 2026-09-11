// Regenerate decisiontree-preview.html from FEPDecisionTree.tsx, so the preview
// is the CSS, the geometry and the contrast maths the component actually ships.
// Same trick as build-preview.js: extract from the source rather than retyping
// it, because a preview that drifts from the component is worse than none.
//
//     node framer/build-decisiontree-preview.js
const fs = require("fs");
const path = require("path");

const here = __dirname;
const src = fs.readFileSync(path.join(here, "FEPDecisionTree.tsx"), "utf8");

// ---- the CSS, verbatim ----------------------------------------------------
const css = src.slice(src.indexOf("const CSS = `") + "const CSS = `".length,
                      src.indexOf("`\n\n// ---"));
for (const token of [".fepdt-fill", ".fepdt-inner", ".fepdt-divider",
                     'legend[data-wide="hidden"]', "container-type:inline-size",
                     "@container (max-width: 520px)"]) {
    if (!css.includes(token)) throw new Error("preview lost " + token);
}

// ---- geometry and contrast, from the component ----------------------------
const helpers = src.slice(src.indexOf("function num("), src.indexOf("const EASINGS"));
const js = helpers
    .replace(/^type RGBA =[^\n]*\n/m, "")
    .replace(/:\s*\{[^}]*\}\[\]/g, "")
    .replace(/\)\s*:\s*\{[^}]*\}\[\]\s*\{/g, ") {")
    .replace(/:\s*RGBA\s*\|\s*null/g, "")
    .replace(/:\s*RGBA\b/g, "")
    .replace(/:\s*LayerKey\b/g, "")
    .replace(/:\s*number\s*\|\s*null/g, "")
    .replace(/:\s*(number|string|unknown|boolean)\b/g, "")
    .replace(/\s+as\s+number\b/g, "");
const m = {};
new Function("exports", js +
    "\nexports.withMinimums=withMinimums;exports.rampOpacity=rampOpacity;" +
    "\nexports.pct=pct;exports.commas=commas;exports.signed=signed;" +
    "\nexports.effectiveLuminance=effectiveLuminance;")(m);

const EASINGS = {};
{
    const block = src.slice(src.indexOf("const EASINGS"), src.indexOf("}", src.indexOf("const EASINGS")));
    for (const [, k, v] of block.matchAll(/(\w+):\s*"([^"]+)"/g)) EASINGS[k] = v;
}

// ---- the two copies of every default must agree --------------------------
// Framer needs literal defaultValues in addPropertyControls and cannot read
// them from the signature, so each one is written twice. Two copies is two
// chances to drift, and a drift is invisible until someone drops a fresh
// instance and gets a different component. So: compare them, and refuse.
function controlDefaults() {
    const block = src.slice(src.indexOf("addPropertyControls(FEPDecisionTree"));
    const out = {};
    const re = /\n    (\w+):\s*\{/g;
    let m;
    while ((m = re.exec(block))) {
        // Walk braces from the opening one, so a one-line control and a control
        // holding a `hidden` arrow function are read the same way.
        let depth = 0, i = block.indexOf("{", m.index + m[0].length - 1), start = i;
        for (; i < block.length; i++) {
            if (block[i] === "{") depth++;
            else if (block[i] === "}") { depth--; if (!depth) break; }
        }
        const body = block.slice(start, i + 1);
        const d = /defaultValue:\s*("(?:[^"\\]|\\.)*"|-?[\d.]+|true|false)/.exec(body);
        if (d) out[m[1]] = d[1];
    }
    return out;
}

function signatureDefaults() {
    const open = src.indexOf("export default function FEPDecisionTree({");
    const sig = src.slice(open, src.indexOf("}: Props) {", open));
    const out = {};
    for (const [, k, v] of sig.matchAll(/\n    (\w+) = ("(?:[^"\\]|\\.)*"|-?[\d.]+|true|false),/g)) {
        out[k] = v;
    }
    return out;
}

{
    const controls = controlDefaults();
    const signature = signatureDefaults();
    const problems = [];
    for (const key of Object.keys(controls)) {
        if (!(key in signature)) {
            problems.push(key + ": control default " + controls[key] + ", signature has none");
        } else if (signature[key] !== controls[key]) {
            problems.push(key + ": signature " + signature[key] + " vs control " + controls[key]);
        }
    }
    if (problems.length) {
        throw new Error("defaults have drifted:\n  " + problems.join("\n  "));
    }
    console.log("defaults agree across " + Object.keys(controls).length + " controls");
}

// ---- defaults, read out of the property controls --------------------------
const def = (name) => {
    const at = src.indexOf("\n    " + name + ": {");
    if (at < 0) throw new Error("no control called " + name);
    const found = /defaultValue:\s*("([^"]*)"|[-\d.]+)/.exec(src.slice(at, at + 700));
    if (!found) throw new Error("no defaultValue on " + name);
    return found[2] !== undefined ? found[2] : parseFloat(found[1]);
};

const INK = def("ink"), MUTED = def("muted"), BASE = def("baseColor");
const SPLIT = def("splitColor"), BG = def("background"), SURFACE = def("surfaceColor");
const FALLOFF = def("rampStrength"), MINSEG = def("minSegment");
const BARH = def("barHeight"), BARR = def("barRadius"), GAP = def("segmentGap");
const PCT_MIN = def("inlineLabelMin"), NAME_MIN = def("inlineNameMin");
const LAYOUT = def("inlineLayout"), LABEL_DARK = def("labelInkDark");
const FULL_MIN = def("inlineFullNameMin");
const DIVIDER = def("dividerColor"), PAD = def("padding"), RAD = def("radius");
const COUNT = def("countColor"), ROWLINE = def("rowLineColor");
const SUBTITLE = def("subtitle");
const DUR = def("revealDuration"), STEP = def("revealStagger");
const EASE = EASINGS[def("revealEasing")] || EASINGS.easeOut;
const AMOUNT = def("revealAmount");

const SHORT = ["Picks", "TB1", "TB2", "TB3", "Tied"];
const LAYERS = [
    ["outright", "Correct Picks"],
    ["tb1", "Tiebreaker 1 - Season Record"],
    ["tb2", "Tiebreaker 2 - Division Record"],
    ["tb3", "Tiebreaker 3 - Points Total"],
    ["split", "Fully tied (even split)"],
];

function card(opts) {
    const { eyebrow, shares, deltas, outcomes, width } = opts;
    const items = LAYERS.map(([k], i) => ({ key: k, share: shares[i] }));
    const segs = m.withMinimums(items, MINSEG);
    const innerR = Math.min(BARR, BARH / 2);

    const bar = segs.map((s, i) => {
        const idx = LAYERS.findIndex((l) => l[0] === s.key);
        const isSplit = s.key === "split";
        const colour = isSplit ? SPLIT : BASE;
        const fade = isSplit ? 1 : m.rampOpacity(idx, FALLOFF);
        const fill = isSplit
            ? `repeating-linear-gradient(135deg, ${colour} 0 6px, transparent 6px 12px)`
            : colour;
        const corners = GAP > 0
            ? `border-top-left-radius:${i === 0 ? BARR : innerR}px;` +
              `border-bottom-left-radius:${i === 0 ? BARR : innerR}px;` +
              `border-top-right-radius:${i === segs.length - 1 ? BARR : innerR}px;` +
              `border-bottom-right-radius:${i === segs.length - 1 ? BARR : innerR}px;`
            : "";

        // Same rule as labelInkFor: blend the fill over the surface, pick by
        // luminance, fall back to the opacity midpoint.
        const lum = m.effectiveLuminance(colour, fade, SURFACE);
        const textInk = (lum === null ? fade >= 0.55 : lum > 0.42) ? LABEL_DARK : INK;

        const enter = i * STEP;
        const inner = s.width >= PCT_MIN
            ? `<span class="fepdt-inner" data-layout="${LAYOUT}" style="color:${textInk};opacity:0;
                 transition:opacity ${Math.round(DUR * 0.5)}ms ease-out ${Math.round(enter + DUR * 0.55)}ms">
                 ${s.width >= NAME_MIN ? `<span class="fepdt-segname">${s.width >= FULL_MIN ? LAYERS[idx][1] : SHORT[idx]}</span>` : ""}
                 <span class="fepdt-segpct">${m.pct(shares[idx], 0)}</span>
               </span>`
            : "";

        return `<div class="fepdt-seg" data-w="${s.width}" style="width:0%;${corners}
                  transition:width ${DUR}ms ${EASE} ${enter}ms, opacity .14s ease"
                  title="${LAYERS[idx][1]} ${m.pct(shares[idx])}">
                  <span class="fepdt-fill" style="background:${fill};opacity:${fade};
                    ${isSplit ? `box-shadow:inset 0 0 0 1px ${colour};` : ""}"></span>
                  ${i > 0 && GAP === 0 ? `<span class="fepdt-divider" style="background:${DIVIDER}"></span>` : ""}
                  ${inner}
                </div>`;
    }).join("");

    const legend = LAYERS.map(([k, name], i) => shares[i] <= 0 ? "" :
        `<div class="fepdt-row" style="border-top-color:${ROWLINE};color:${INK};opacity:0;
            transform:translateY(4px);
            transition:opacity ${Math.round(DUR * 0.6)}ms ease-out ${Math.round(i * STEP + DUR * 0.4)}ms,
                       transform ${Math.round(DUR * 0.6)}ms ${EASE} ${Math.round(i * STEP + DUR * 0.4)}ms">
           <span class="fepdt-swatch" style="background:${k === "split" ? SPLIT : BASE};opacity:${k === "split" ? 1 : m.rampOpacity(i, FALLOFF)}"></span>
           <span class="fepdt-name">${name}</span>
           <span class="fepdt-count" style="color:${COUNT}">${m.commas(shares[i] / 100 * outcomes)} of ${m.commas(outcomes)}</span>
           <span class="fepdt-share">${m.pct(shares[i])}</span>
           ${deltas ? `<span class="fepdt-delta" style="color:${MUTED}">${m.signed(deltas[i])}</span>` : ""}
         </div>`).join("");

    return `<div style="width:${width}px;flex:none">
  <p class="caption">${width}px</p>
  <div class="fepdt" style="font-family:'Maven Pro',sans-serif;font-size:14px;
       background:${BG};color:${INK};border-radius:${RAD}px;padding:${PAD}px">
    <p class="fepdt-eyebrow" style="color:${MUTED}">${eyebrow}</p>
    <h3 class="fepdt-title">Decision Tree</h3>
    <p class="fepdt-sub" style="color:${MUTED}">${SUBTITLE.replace("{N}", m.commas(outcomes))}</p>
    <div class="fepdt-bar" style="height:${BARH}px;border-radius:${BARR}px;gap:${GAP}px">${bar}</div>
    <div class="fepdt-legend" data-wide="shown">${legend}</div>
    ${deltas ? `<p class="fepdt-note" style="color:${MUTED}">Change against Week 9.</p>` : ""}
  </div>
</div>`;
}

const PRESEASON = { eyebrow: "2026 | Preseason", shares: [62.0, 16.6, 9.1, 12.4, 0],
                    deltas: null, outcomes: 131072 };
const WEEK10 = { eyebrow: "2025 | Week 10", shares: [42.1, 38.3, 17.0, 2.7, 0],
                 deltas: [-14.3, 13.1, 6.9, -5.6, 0], outcomes: 256 };

const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FEP Decision Tree preview</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Maven+Pro:wght@400;500;600;700;800&display=swap">
<style>
body{margin:0;padding:28px;background:#0b1512;font-family:'Maven Pro',sans-serif}
h1{color:#eafaf6;font-size:17px;font-weight:800;margin:0 0 4px}
h1+p{color:#7f9c96;font-size:13px;margin:0 0 20px;max-width:74ch;line-height:1.55}
button{font:inherit;font-size:12px;font-weight:700;color:#06231f;background:#4ED9B0;
  border:0;border-radius:8px;padding:8px 14px;cursor:pointer;margin:0 0 24px}
.caption{color:#55706b;font-size:11px;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;margin:0 0 8px}
.grid{display:flex;flex-wrap:wrap;gap:28px;align-items:flex-start}
${css}
</style></head><body>
<h1>FEP Decision Tree</h1>
<p>Generated from FEPDecisionTree.tsx by build-decisiontree-preview.js, so this is
the shipping CSS, the shipping geometry and the shipping contrast rule. The 360px
cards are the mobile case: the text comes out of the bar and the legend carries it.
The 2025 Week 10 card is the geometry case: TB3 is really 2.7% and is drawn at the
4% floor, while the legend still reports the true number.</p>
<button onclick="replay()">Replay the reveal</button>
<div class="grid">
  ${card({ ...WEEK10, width: 640 })}
  ${card({ ...WEEK10, width: 360 })}
  ${card({ ...PRESEASON, width: 640 })}
  ${card({ ...PRESEASON, width: 360 })}
</div>
<script>
// The same reveal the component runs: grow each segment to its width on a
// stagger, fade its text in once it has mostly landed.
var AMOUNT = ${AMOUNT};
function show(card, on) {
  card.querySelectorAll('.fepdt-seg').forEach(function (seg) {
    seg.style.width = (on ? seg.getAttribute('data-w') : 0) + '%';
  });
  card.querySelectorAll('.fepdt-inner').forEach(function (el) {
    el.style.opacity = on ? 1 : 0;
  });
  card.querySelectorAll('.fepdt-row').forEach(function (el) {
    el.style.opacity = on ? 1 : 0;
    el.style.transform = on ? 'none' : 'translateY(4px)';
  });
}
var cards = [].slice.call(document.querySelectorAll('.fepdt'));
if (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) {
  cards.forEach(function (c) { show(c, true); });
} else if (typeof IntersectionObserver === 'function') {
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { if (e.isIntersecting) show(e.target, true); });
  }, { threshold: [0, AMOUNT], rootMargin: '0px 0px -15% 0px' });
  cards.forEach(function (c) { io.observe(c); });
} else {
  cards.forEach(function (c) { show(c, true); });
}
function replay() {
  cards.forEach(function (c) { show(c, false); });
  setTimeout(function () { cards.forEach(function (c) { show(c, true); }); }, 80);
}
</script>
</body></html>`;

const out = path.join(here, "decisiontree-preview.html");
fs.writeFileSync(out, html);
console.log("wrote " + out + " (" + html.length + " bytes)");
