// Regenerate newsegments-preview.html from FEPLeverageSpine.tsx and
// FEPUnderTheHood.tsx, using each component's own CSS and its own control
// defaults. Same arrangement as the other two preview builders: extract rather
// than retype, so the preview cannot drift from what ships.
//
//     node framer/build-newsegments-preview.js
const fs = require("fs");
const path = require("path");
const here = __dirname;

const read = (f) => fs.readFileSync(path.join(here, f), "utf8");
const spine = read("FEPLeverageSpine.tsx");
const hood = read("FEPUnderTheHood.tsx");

const cssOf = (src, marks) => {
    const css = src.slice(src.indexOf("const CSS = `") + 13,
                          src.indexOf("`\n\n", src.indexOf("const CSS = `")));
    for (const m of marks) if (!css.includes(m)) throw new Error("preview lost " + m);
    return css;
};
const spineCss = cssOf(spine, [".fepls-bar", "@container (max-width: 620px)"]);
const hoodCss = cssOf(hood, [".feputh-body", "grid-template-rows:0fr"]);

const defOf = (src) => (name) => {
    const at = src.indexOf("\n    " + name + ": {");
    if (at < 0) throw new Error("no control " + name);
    const found = /defaultValue:\s*("(?:[^"\\]|\\.)*"|-?[\d.]+|true|false)/
        .exec(src.slice(at, at + 900));
    if (!found) throw new Error("no defaultValue on " + name);
    return found[1][0] === '"' ? JSON.parse(found[1]) : JSON.parse(found[1]);
};
const S = defOf(spine);

// ---- the spine ------------------------------------------------------------
const split = (s) => String(s).split(",").map((x) => x.trim());
const LABELS = split(S("labels"));
const VALUES = split(S("leverages")).map(Number);
const RESULTS = split(S("results"));
// The component's own short labels, so the preview shows what ships.
const SHORTS = split(S("shortLabels"));
const short = (label, i) => SHORTS[i] || label;

function spineCard(width, opts) {
    const o = Object.assign({
        plotH: S("plotHeight"), gap: S("barGap"), barR: S("barRadius"),
        rem: S("remainingColor"), next: S("nextColor"), win: S("winColor"),
        loss: S("lossColor"), ink: S("ink"), muted: S("muted"),
        bg: S("background"), pad: S("padding"), rad: S("radius"),
        base: S("baselineColor"), fade: S("playedOpacity"),
        dur: S("revealDuration"), step: S("revealStagger"),
    }, opts || {});
    const nextIdx = RESULTS.findIndex((r) => !r);
    const ceiling = Math.max(...VALUES);
    const usable = Math.max(10, o.plotH - Math.round(14 * 1.2));
    const remaining = VALUES.map((v, i) => (RESULTS[i] ? -1 : v));
    const topIdx = remaining.indexOf(Math.max(...remaining));
    const notable = new Set([nextIdx, topIdx]);
    const suffix = S("valueSuffix");

    const cols = LABELS.map((label, i) => {
        const r = (RESULTS[i] || "").toUpperCase();
        const isNext = i === nextIdx;
        const c = r === "W" ? o.win : r === "L" ? o.loss : isNext ? o.next : o.rem;
        const h = Math.round((VALUES[i] / ceiling) * usable);
        const valInk = r ? o.muted : isNext ? o.next : o.ink;
        const val = notable.has(i)
            ? `<span class="fepls-val" style="color:${valInk};opacity:0;
        transition:opacity ${Math.round(o.dur*0.5)}ms ease-out ${Math.round(i*o.step+o.dur*0.5)}ms">${VALUES[i].toFixed(0)}${suffix}</span>`
            : "";
        return `<div class="fepls-col">
      ${val}
      <span class="fepls-barwrap"><span class="fepls-bar" data-bar
        style="height:${h}px;background:${c};opacity:${r ? o.fade : 1};
        border-radius:${o.barR}px ${o.barR}px 0 0;transform:scaleY(0);
        ${isNext ? `box-shadow:0 0 0 2px ${o.next}66;` : ""}
        transition:transform ${o.dur}ms cubic-bezier(0.22,1,0.36,1) ${i*o.step}ms"></span></span>
    </div>`;
    }).join("");

    const strip = LABELS.map((_, i) => {
        const r = (RESULTS[i] || "").toUpperCase();
        const c = r === "W" ? o.win : r === "L" ? o.loss : i === nextIdx ? o.next : o.muted;
        return `<span class="fepls-cell"><span class="fepls-res" style="color:${c};opacity:0;
          transition:opacity ${Math.round(o.dur*0.5)}ms ease-out ${Math.round(i*o.step+o.dur*0.4)}ms">${r || ""}</span></span>`;
    }).join("");

    const names = LABELS.map((l, i) =>
        `<span class="fepls-name" data-tier="full" style="color:${i===nextIdx?o.ink:o.muted}">${l}</span>`).join("")
      + LABELS.map((l, i) =>
        `<span class="fepls-name" data-tier="short" style="color:${i===nextIdx?o.ink:o.muted}">${short(l, i)}</span>`).join("");

    const key = [["Still to play", o.rem], ["Next up", o.next], ["Won", o.win], ["Lost", o.loss]]
        .map(([t, c]) => `<span class="fepls-keyitem"><span class="fepls-keydot" style="background:${c}"></span>${t}</span>`).join("");

    const foot = S("foot").replace("{topLabel}", LABELS[topIdx])
                          .replace("{topValue}", VALUES[topIdx].toFixed(1) + "%");

    return `<div style="width:${width}px;flex:none">
  <p class="caption">${width}px</p>
  <div class="fepls" style="font-family:'Maven Pro',sans-serif;font-size:14px;background:${o.bg};
       color:${o.ink};border-radius:${o.rad}px;padding:${o.pad}px">
    <p class="fepls-eyebrow" style="color:${o.muted}">2026 | Week 3</p>
    <h3 class="fepls-title">${S("title")}</h3>
    <p class="fepls-sub" style="color:${o.muted}">${S("subtitle")}</p>
    <p class="fepls-caption" style="color:${o.muted}">${S("axisCaption")}</p>
    <div class="fepls-plot" data-vmode="notable" style="height:${o.plotH}px;gap:${o.gap}px">${cols}</div>
    <div class="fepls-baseline" style="background:${o.base}"></div>
    <div class="fepls-strip" style="gap:${o.gap}px">${strip}</div>
    <div class="fepls-names" style="gap:${o.gap}px">${names}</div>
    <div class="fepls-key" style="color:${o.muted}">${key}</div>
    <p class="fepls-foot">${foot}</p>
  </div>
</div>`;
}

// ---- the drawer -----------------------------------------------------------
const H = defOf(hood);
const TILES = (() => {
    const block = hood.slice(hood.indexOf("const TILE_DEFAULTS"), hood.indexOf("const tileControls"));
    const out = [];
    for (const m of block.matchAll(/\n    \d+: \{([\s\S]*?)\n    \},/g)) {
        const b = m[1];
        const g = (k) => {
            const r = new RegExp(k + ":\\s*\\n?\\s*(\"(?:[^\"\\\\]|\\\\.)*\"|true|false)").exec(b);
            return r ? (r[1][0] === '"' ? JSON.parse(r[1]) : r[1] === "true") : "";
        };
        out.push({ on: g("on") === true, label: g("label"), value: g("value"),
                   gloss: g("gloss"), accent: g("accent") });
    }
    return out.filter((t) => t.on);
})();

function hoodCard(width, collapsible) {
    const accent = (a) => a === "good" ? H("goodColor") : a === "bad" ? H("badColor") : H("neutralColor");
    const openNow = !collapsible;
    const tiles = TILES.map((t, i) => `<div class="feputh-tile" style="background:${H("tileBackground")};
      border-radius:${H("tileRadius")}px;border-left:3px solid ${accent(t.accent)};
      opacity:${openNow ? 0 : 0};transform:translateY(6px);
      transition:opacity ${Math.round(H("duration")*0.8)}ms ease-out ${i*H("tileStagger")}ms,
                 transform ${Math.round(H("duration")*0.8)}ms cubic-bezier(0.22,1,0.36,1) ${i*H("tileStagger")}ms">
      <p class="feputh-label" style="color:${H("labelColor")}">${t.label}</p>
      <p class="feputh-value" style="color:${accent(t.accent)}">${t.value}</p>
      <p class="feputh-gloss" style="color:${H("glossColor")}">${t.gloss}</p>
    </div>`).join("");

    const chev = collapsible ? `<span class="feputh-chev" style="color:${H("muted")};
        transition:transform ${H("duration")}ms cubic-bezier(0.22,1,0.36,1)">
        <svg width="13" height="8" viewBox="0 0 13 8"><path d="M1 1l5.5 5.5L12 1" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </span>` : "";

    const head = `<div class="feputh-head" ${collapsible ? 'role="button" style="cursor:pointer" onclick="toggleHood(this)"' : 'style="cursor:default"'}>
      <span class="feputh-heading">
        <span class="feputh-title" style="display:block">${H("title")}</span>
        <span class="feputh-hint" style="color:${H("muted")};display:block;margin-top:3px">${H("hint")}</span>
      </span>${chev}
    </div>`;

    return `<div style="width:${width}px;flex:none">
  <p class="caption">${width}px ${collapsible ? "collapsible" : "always open"}</p>
  <div class="feputh" data-hood data-collapsible="${collapsible}" style="font-family:'Maven Pro',sans-serif;
       font-size:14px;background:#06231f;color:${H("ink")};border-radius:14px;padding:18px">
    ${head}
    <div class="feputh-body" style="grid-template-rows:${openNow ? "1fr" : "0fr"};
         ${collapsible ? `transition:grid-template-rows ${H("duration")}ms cubic-bezier(0.22,1,0.36,1);` : ""}">
      <div class="feputh-clip"><div style="padding-top:14px">
        <div class="feputh-tiles" style="gap:${H("tileGap")}px">${tiles}</div>
      </div></div>
    </div>
  </div>
</div>`;
}

const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FEP new segments preview</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Maven+Pro:wght@400;500;600;700;800&display=swap">
<style>
body{margin:0;padding:26px;background:#0b1512;font-family:'Maven Pro',sans-serif}
h1{color:#eafaf6;font-size:17px;font-weight:800;margin:0 0 4px}
h2{color:#eafaf6;font-size:14px;font-weight:800;margin:30px 0 14px}
p.lede{color:#7f9c96;font-size:13px;margin:0 0 18px;max-width:78ch;line-height:1.55}
button.replay{font:inherit;font-size:12px;font-weight:700;color:#06231f;background:#4ED9B0;
  border:0;border-radius:8px;padding:8px 14px;cursor:pointer;margin:0 0 10px}
.caption{color:#55706b;font-size:11px;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;margin:0 0 8px}
.grid{display:flex;flex-wrap:wrap;gap:26px;align-items:flex-start}
${spineCss}
${hoodCss}
</style></head><body>
<h1>Leverage Spine and Under the Hood</h1>
<p class="lede">Generated from FEPLeverageSpine.tsx and FEPUnderTheHood.tsx by
build-newsegments-preview.js, so the CSS, the colours and the copy are the ones the
components ship with. Click a drawer header to open it. Sample season: three games
played, the rest to come.</p>
<button class="replay" onclick="replay()">Replay the reveal</button>
<h2>Leverage Index</h2>
<div class="grid">${spineCard(720)}${spineCard(560)}${spineCard(360)}</div>
<h2>Under the Hood</h2>
<div class="grid">${hoodCard(720, false)}${hoodCard(360, false)}${hoodCard(560, true)}</div>
<script>
function show(on){
  document.querySelectorAll('[data-bar]').forEach(function(b){
    b.style.transform = on ? 'scaleY(1)' : 'scaleY(0)';
  });
  document.querySelectorAll('.fepls-val,.fepls-res').forEach(function(e){
    e.style.opacity = on ? 1 : 0;
  });
}
function replay(){ show(false); setTimeout(function(){ show(true); }, 80); }
function revealHoods(){
  document.querySelectorAll('[data-collapsible="false"] .feputh-tile').forEach(function(t){
    t.style.opacity = 1; t.style.transform = 'none';
  });
}
function toggleHood(btn){
  var card = btn.closest('[data-hood]');
  var body = card.querySelector('.feputh-body');
  var open = body.style.gridTemplateRows === '1fr';
  body.style.gridTemplateRows = open ? '0fr' : '1fr';
  card.querySelector('.feputh-chev').style.transform = open ? 'none' : 'rotate(180deg)';
  card.querySelectorAll('.feputh-tile').forEach(function(t){
    t.style.opacity = open ? 0 : 1;
    t.style.transform = open ? 'translateY(6px)' : 'none';
  });
}
if (typeof IntersectionObserver === 'function') {
  var io = new IntersectionObserver(function(es){
    es.forEach(function(e){ if (e.isIntersecting) show(true); });
  }, { threshold:[0,0.35], rootMargin:'0px 0px -15% 0px' });
  document.querySelectorAll('.fepls').forEach(function(c){ io.observe(c); });
  var io2 = new IntersectionObserver(function(es){
    es.forEach(function(e){ if (e.isIntersecting) revealHoods(); });
  }, { threshold:[0,0.35], rootMargin:'0px 0px -15% 0px' });
  document.querySelectorAll('[data-collapsible="false"]').forEach(function(c){ io2.observe(c); });
} else { show(true); revealHoods(); }
</script>
</body></html>`;

const out = path.join(here, "newsegments-preview.html");
fs.writeFileSync(out, html);
console.log("wrote " + out + " (" + html.length + " bytes)");
