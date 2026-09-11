import { addPropertyControls, ControlType, RenderTarget } from "framer"
import { useEffect, useMemo, useRef, useState } from "react"

/**
 * FEP Decision Tree
 * =================
 *
 * One horizontal stacked bar: of every way the rest of the season can still go,
 * what fraction is settled on correct picks, and what fraction falls through to
 * each tiebreaker.
 *
 * Why every number is a prop
 * --------------------------
 * Framer's CMS binding reaches text, images, links and visibility. It does NOT
 * reach a layer's width, which is exactly what a stacked bar needs. A code
 * component's PROPERTIES can be bound to CMS fields, so the five shares are
 * props here rather than layers. Bind them to fields on the `weeks` collection
 * and the bar sizes itself from the sheet.
 *
 * Two sources, and manual is the default:
 *
 *   Manual   the five shares come from props. Bind them to CMS number fields.
 *            Works today, with no change to the publish step.
 *   Auto     fetch {baseUrl}/{year}/week-NN.json and read `deciding` out of it.
 *            Needs the payload change; the component degrades to a notice
 *            until that field exists.
 *
 * Shares are normalised to 100 before drawing, so CMS rounding that sums to
 * 99.9 or 100.1 cannot produce a short or overflowing bar.
 *
 * Mobile
 * ------
 * The bar is the signature of the segment, so it survives at every width. What
 * changes is the labelling: the text inside the segments is pulled out below
 * 520px and the legend carries it instead. Driven by container queries, so it
 * responds to the frame it is in rather than the size of the phone.
 *
 * The legend is always in the DOM for that reason. Turning it off hides it on
 * wide frames only, because a narrow frame with no legend and no inline text
 * would be a bar with no labels at all.
 *
 * The reveal
 * ----------
 * Each segment grows from zero to its width, one after another, so the bar
 * fills left to right and every layer gets its own beat. The text inside a
 * segment fades in once that segment has mostly arrived. Fires when the bar
 * scrolls into view, by default once, at whatever fraction you set.
 *
 * Plain CSS transitions rather than an animation library, so the same timing
 * can be mirrored in the static preview. Honours prefers-reduced-motion, and
 * skips the animation entirely on the Framer canvas so it can be styled.
 *
 * House rule: no em dashes and no en dashes in any string this renders.
 */

const FONT_URL =
    "https://fonts.googleapis.com/css2?family=Maven+Pro:wght@400;500;600;700;800&display=swap"

type LayerKey = "outright" | "tb1" | "tb2" | "tb3" | "split"

const LAYERS: { key: LayerKey; label: string; short: string }[] = [
    { key: "outright", label: "Correct Picks", short: "Picks" },
    { key: "tb1", label: "Tiebreaker 1 - Season Record", short: "TB1" },
    { key: "tb2", label: "Tiebreaker 2 - Division Record", short: "TB2" },
    { key: "tb3", label: "Tiebreaker 3 - Points Total", short: "TB3" },
    { key: "split", label: "Fully tied (even split)", short: "Tied" },
]

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

/** Load Maven Pro once per document, whatever how many instances are on a page. */
function useWebFont(href: string, enabled: boolean) {
    useEffect(() => {
        if (!enabled || typeof document === "undefined") return
        if (document.querySelector('link[data-fep-font="maven-pro"]')) return
        const link = document.createElement("link")
        link.rel = "stylesheet"
        link.href = href
        link.setAttribute("data-fep-font", "maven-pro")
        document.head.appendChild(link)
    }, [href, enabled])
}

function num(value: unknown, fallback = 0): number {
    const n = typeof value === "string" ? parseFloat(value) : (value as number)
    return typeof n === "number" && isFinite(n) ? n : fallback
}

function pct(value: number, digits = 1): string {
    return value.toFixed(digits) + "%"
}

function signed(value: number | null): string {
    if (value === null || !isFinite(value)) return ""
    const rounded = Math.round(value * 10) / 10
    if (rounded === 0) return "0.0"
    return (rounded > 0 ? "+" : "") + rounded.toFixed(1)
}

function commas(value: number): string {
    return Math.round(value).toLocaleString("en-US")
}

/**
 * Give every visible segment a floor, so a 2.7% tiebreaker is still a thing you
 * can see and point at. The deficit comes off the segments that have room,
 * proportionally, so the bar still sums to exactly 100.
 */
function withMinimums(
    items: { key: LayerKey; share: number }[],
    minPct: number
): { key: LayerKey; share: number; width: number }[] {
    const visible = items.filter((i) => i.share > 0)
    if (!visible.length) return []

    const total = visible.reduce((sum, i) => sum + i.share, 0) || 1
    const widths = visible.map((i) => (i.share / total) * 100)

    // Never demand a floor the bar cannot pay for.
    const floor = Math.min(minPct, 100 / visible.length)

    let deficit = 0
    const raised = widths.map((w) => {
        if (w < floor) {
            deficit += floor - w
            return floor
        }
        return w
    })

    if (deficit > 0) {
        const room = raised.map((w) => Math.max(0, w - floor))
        const pool = room.reduce((sum, r) => sum + r, 0)
        if (pool > 0) {
            for (let i = 0; i < raised.length; i++) {
                raised[i] -= (room[i] / pool) * deficit
            }
        }
    }

    return visible.map((item, i) => ({ ...item, width: raised[i] }))
}

/** Geometric falloff, so each rung of the cascade reads as one step further down. */
function rampOpacity(index: number, strength: number): number {
    return Math.pow(Math.max(0.15, Math.min(1, strength)), index)
}

type RGBA = { r: number; g: number; b: number; a: number }

/** Framer hands colours over as hex or as rgb()/rgba(). Both, or nothing. */
function parseColor(input: string): RGBA | null {
    if (!input) return null
    const text = String(input).trim()

    const hex = /^#([0-9a-fA-F]{3,8})$/.exec(text)
    if (hex) {
        let h = hex[1]
        if (h.length === 3 || h.length === 4) {
            h = h.split("").map((c) => c + c).join("")
        }
        if (h.length < 6) return null
        return {
            r: parseInt(h.slice(0, 2), 16),
            g: parseInt(h.slice(2, 4), 16),
            b: parseInt(h.slice(4, 6), 16),
            a: h.length >= 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1,
        }
    }

    const rgb = /^rgba?\(([^)]+)\)$/i.exec(text)
    if (rgb) {
        const parts = rgb[1].split(/[ ,\/]+/).filter(Boolean).map(parseFloat)
        if (parts.length >= 3 && parts.every((n) => isFinite(n))) {
            return {
                r: parts[0],
                g: parts[1],
                b: parts[2],
                a: parts.length > 3 ? parts[3] : 1,
            }
        }
    }
    return null
}

function relativeLuminance(c: RGBA): number {
    const channel = (v: number) => {
        const x = Math.max(0, Math.min(255, v)) / 255
        return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4)
    }
    return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b)
}

/**
 * What the eye actually sees where a faded fill sits on the card. The ramp
 * means the same colour is near-solid at the top of the cascade and nearly the
 * background at the bottom, so contrast has to be judged per segment, after the
 * blend, not once for the whole bar.
 */
function effectiveLuminance(
    fill: string,
    alpha: number,
    surface: string
): number | null {
    const top = parseColor(fill)
    const under = parseColor(surface)
    if (!top || !under) return null
    const a = Math.max(0, Math.min(1, top.a * alpha))
    return relativeLuminance({
        r: top.r * a + under.r * (1 - a),
        g: top.g * a + under.g * (1 - a),
        b: top.b * a + under.b * (1 - a),
        a: 1,
    })
}

const EASINGS: Record<string, string> = {
    easeOut: "cubic-bezier(0.22, 1, 0.36, 1)",
    easeInOut: "cubic-bezier(0.65, 0, 0.35, 1)",
    overshoot: "cubic-bezier(0.34, 1.56, 0.64, 1)",
    linear: "linear",
}

/**
 * True once the bar has been in view by at least `amount`. Set `replay` and it
 * goes back to false on the way out, so scrolling up and down replays it.
 *
 * Three cases skip the animation and start in the finished state: the Framer
 * canvas (so it can be styled), a reader who asked for reduced motion, and mode
 * "off".
 */
function useReveal(
    mode: string,
    amount: number,
    replay: boolean
): [any, boolean, boolean] {
    const ref = useRef<HTMLDivElement | null>(null)

    const isCanvas =
        typeof RenderTarget !== "undefined" &&
        RenderTarget.current() === RenderTarget.canvas

    const reduced =
        typeof window !== "undefined" &&
        typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches

    const still = mode === "off" || isCanvas || reduced
    const [shown, setShown] = useState(still || mode === "onLoad")

    useEffect(() => {
        if (still) {
            setShown(true)
            return
        }
        if (mode === "onLoad") {
            // One frame late, so the transition has a zero state to leave.
            const id = requestAnimationFrame(() => setShown(true))
            return () => cancelAnimationFrame(id)
        }

        const node = ref.current
        if (!node || typeof IntersectionObserver === "undefined") {
            setShown(true)
            return
        }

        const threshold = Math.max(0, Math.min(1, amount))
        const observer = new IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    if (entry.isIntersecting) {
                        setShown(true)
                        if (!replay) observer.unobserve(entry.target)
                    } else if (replay) {
                        setShown(false)
                    }
                }
            },
            // A tall bar can never cross a high threshold on a short screen, so
            // the threshold is paired with a margin that also fires once the
            // top third of the viewport has it.
            { threshold: [0, threshold], rootMargin: "0px 0px -15% 0px" }
        )
        observer.observe(node)
        return () => observer.disconnect()
    }, [mode, amount, replay, still])

    return [ref, shown, still]
}

// ---------------------------------------------------------------------------
// auto mode
// ---------------------------------------------------------------------------

type Fetched = {
    shares: Record<LayerKey, number>
    deltas: Record<LayerKey, number | null>
    outcomes: number | null
    baselineWeek: number | null
}

function useFetchedDeciding(
    enabled: boolean,
    baseUrl: string,
    year: number,
    week: number
) {
    const [state, setState] = useState<{
        data: Fetched | null
        error: string | null
        loading: boolean
    }>({ data: null, error: null, loading: false })

    useEffect(() => {
        if (!enabled) {
            setState({ data: null, error: null, loading: false })
            return
        }
        if (!baseUrl) {
            setState({ data: null, error: "Set the data base URL.", loading: false })
            return
        }

        const root = baseUrl.replace(/\/+$/, "")
        // A base URL that already ends in the year still works, same as the chart.
        const withYear = new RegExp("/" + year + "$").test(root)
            ? root
            : root + "/" + year
        const url =
            withYear + "/week-" + String(week).padStart(2, "0") + ".json"

        let cancelled = false
        setState({ data: null, error: null, loading: true })

        fetch(url)
            .then((r) => {
                if (!r.ok) throw new Error("HTTP " + r.status)
                return r.json()
            })
            .then((payload: any) => {
                if (cancelled) return
                const deciding = payload && payload.deciding
                if (!deciding || !Array.isArray(deciding.rows)) {
                    setState({
                        data: null,
                        error:
                            "week-" +
                            String(week).padStart(2, "0") +
                            ".json has no deciding layer yet.",
                        loading: false,
                    })
                    return
                }
                const shares = {} as Record<LayerKey, number>
                const deltas = {} as Record<LayerKey, number | null>
                for (const layer of LAYERS) {
                    shares[layer.key] = 0
                    deltas[layer.key] = null
                }
                for (const row of deciding.rows) {
                    const key = row && (row.key as LayerKey)
                    if (!key || !(key in shares)) continue
                    shares[key] = num(row.share)
                    deltas[key] =
                        row.delta === null || row.delta === undefined
                            ? null
                            : num(row.delta)
                }
                setState({
                    data: {
                        shares,
                        deltas,
                        outcomes:
                            deciding.outcomes != null
                                ? num(deciding.outcomes)
                                : payload.remaining_outcomes != null
                                  ? num(payload.remaining_outcomes)
                                  : null,
                        baselineWeek:
                            deciding.baseline_week != null
                                ? num(deciding.baseline_week)
                                : null,
                    },
                    error: null,
                    loading: false,
                })
            })
            .catch((e) => {
                if (!cancelled) {
                    setState({
                        data: null,
                        error: "Could not load " + url + " (" + e.message + ")",
                        loading: false,
                    })
                }
            })

        return () => {
            cancelled = true
        }
    }, [enabled, baseUrl, year, week])

    return state
}

// ---------------------------------------------------------------------------
// styles
// ---------------------------------------------------------------------------

const CSS = `
.fepdt{container-type:inline-size;box-sizing:border-box}
.fepdt *{box-sizing:border-box}
.fepdt-eyebrow{font-size:.78em;font-weight:700;letter-spacing:.09em;
  text-transform:uppercase;margin:0 0 6px}
.fepdt-title{font-size:1.5em;font-weight:800;letter-spacing:-.01em;margin:0}
.fepdt-sub{font-size:.95em;line-height:1.45;margin:6px 0 0;max-width:60ch}
.fepdt-bar{display:flex;width:100%;overflow:hidden;margin-top:18px;
  position:relative}
.fepdt-seg{position:relative;display:flex;align-items:center;
  justify-content:center;min-width:0;overflow:hidden;cursor:default}
.fepdt-seg[data-dim="1"]{opacity:.28}
/* The cascade fade is a property of the FILL, not of the segment. Putting it on
   the segment fades the text with it, and the faintest rung is exactly where
   the number most needs to stay readable. */
.fepdt-fill{position:absolute;inset:0;border-radius:inherit}
.fepdt-divider{position:absolute;left:0;top:0;bottom:0;width:1px;z-index:2}
.fepdt-inner{position:relative;z-index:3;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:1px;padding:0 10px;
  max-width:100%;text-align:center;pointer-events:none}
.fepdt-inner[data-layout="inline"]{flex-direction:row;align-items:baseline;
  gap:7px}
.fepdt-segname{font-size:.7em;font-weight:700;letter-spacing:.07em;
  text-transform:uppercase;max-width:100%;opacity:.82;line-height:1.25;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
  overflow:hidden}
.fepdt-inner[data-layout="inline"] .fepdt-segname{-webkit-line-clamp:1}
.fepdt-segpct{font-size:1.2em;font-weight:800;line-height:1.15;
  font-variant-numeric:tabular-nums;white-space:nowrap}
.fepdt-legend{display:grid;gap:2px;margin-top:16px}
.fepdt-legend[data-wide="hidden"]{display:none}
.fepdt-row{display:flex;align-items:baseline;gap:10px;padding:7px 0;
  border-top:1px solid currentColor}
.fepdt-row[data-dim="1"]{opacity:.35}
.fepdt-swatch{flex:none;width:11px;height:11px;border-radius:3px;
  align-self:center}
.fepdt-name{flex:1 1 auto;font-size:.92em;font-weight:600;min-width:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fepdt-count{font-size:.82em;font-variant-numeric:tabular-nums;
  white-space:nowrap}
.fepdt-share{font-size:.98em;font-weight:800;font-variant-numeric:tabular-nums;
  text-align:right;min-width:4.2em;white-space:nowrap}
.fepdt-delta{font-size:.82em;font-weight:700;font-variant-numeric:tabular-nums;
  text-align:right;min-width:3.6em;white-space:nowrap}
.fepdt-note{font-size:.82em;margin:10px 0 0}
.fepdt-notice{display:flex;align-items:center;justify-content:center;
  min-height:110px;text-align:center;font-size:.92em;line-height:1.5;
  opacity:.85;padding:16px}

/* Narrow frames. The bar survives, the text comes out of it and the legend
   carries the labelling instead, which is why the legend is always rendered
   and only hidden on wide frames. */
@container (max-width: 520px){
  .fepdt-inner{display:none}
  .fepdt-legend[data-wide="hidden"]{display:grid}
  .fepdt-title{font-size:1.28em}
  .fepdt-name{white-space:normal}
  .fepdt-count{display:none}
}
@container (max-width: 360px){
  .fepdt-delta{display:none}
}
@media (prefers-reduced-motion: reduce){
  .fepdt-seg,.fepdt-inner,.fepdt-row{transition:none !important}
}
`

// ---------------------------------------------------------------------------
// component
// ---------------------------------------------------------------------------

type Props = {
    source?: "manual" | "auto"
    year?: number
    week?: number
    baseUrl?: string
    outright?: number
    tb1?: number
    tb2?: number
    tb3?: number
    split?: number
    outcomes?: number
    showDeltas?: boolean
    baselineWeek?: number | null
    dOutright?: number
    dTb1?: number
    dTb2?: number
    dTb3?: number
    dSplit?: number
    showEyebrow?: boolean
    eyebrow?: string
    showTitle?: boolean
    title?: string
    showSubtitle?: boolean
    subtitle?: string
    showLegend?: boolean
    showCounts?: boolean
    showInlineLabels?: boolean
    inlineLayout?: "stacked" | "inline"
    useShortNames?: boolean
    inlineFullNameMin?: number
    inlineNameMin?: number
    inlineLabelMin?: number
    labelInkMode?: "auto" | "light" | "dark"
    labelInkDark?: string
    surfaceColor?: string
    labelOutright?: string
    labelTb1?: string
    labelTb2?: string
    labelTb3?: string
    labelSplit?: string
    fontFamily?: string
    fontSize?: number
    background?: string
    ink?: string
    muted?: string
    countColor?: string
    rowLineColor?: string
    radius?: number
    padding?: number
    rampMode?: "ramp" | "custom"
    baseColor?: string
    rampStrength?: number
    colorOutright?: string
    colorTb1?: string
    colorTb2?: string
    colorTb3?: string
    splitColor?: string
    barHeight?: number
    barRadius?: number
    segmentGap?: number
    showDividers?: boolean
    dividerColor?: string
    minSegment?: number
    reveal?: "inView" | "onLoad" | "off"
    revealAmount?: number
    revealReplay?: boolean
    revealDuration?: number
    revealStagger?: number
    revealEasing?: string
    style?: React.CSSProperties
}

/**
 * Framer reads these annotations from the comment directly above the exported
 * component, so they have to live here rather than in the file header.
 *
 * Every default is repeated in `addPropertyControls` below, because Framer
 * needs literal `defaultValue`s there and cannot read them from the signature.
 * Two copies is two chances to drift, so `build-decisiontree-preview.js`
 * compares them and refuses to build when they disagree.
 *
 * @framerSupportedLayoutWidth any
 * @framerSupportedLayoutHeight auto
 * @framerIntrinsicWidth 640
 * @framerIntrinsicHeight 300
 */
export default function FEPDecisionTree({
    source = "manual",
    year = 2026,
    week = 1,
    baseUrl = "",
    outright = 62,
    tb1 = 16.6,
    tb2 = 9.1,
    tb3 = 12.4,
    split = 0,
    outcomes = 131072,
    showDeltas = false,
    baselineWeek = 0,
    dOutright = 0,
    dTb1 = 0,
    dTb2 = 0,
    dTb3 = 0,
    dSplit = 0,
    showEyebrow = true,
    eyebrow = "",
    showTitle = true,
    title = "Decision Tree",
    showSubtitle = true,
    subtitle = "All {N} ways this season can still end, sorted by what actually decides them.",
    showLegend = true,
    showCounts = true,
    showInlineLabels = true,
    inlineLayout = "stacked",
    useShortNames = false,
    inlineFullNameMin = 30,
    inlineNameMin = 16,
    inlineLabelMin = 6,
    labelInkMode = "auto",
    labelInkDark = "#06231f",
    surfaceColor = "#06231f",
    labelOutright = "",
    labelTb1 = "",
    labelTb2 = "",
    labelTb3 = "",
    labelSplit = "",
    fontFamily = "Maven Pro",
    fontSize = 14,
    background = "linear-gradient(160deg,#04302a,#06231f)",
    ink = "#eafaf6",
    muted = "#7f9c96",
    countColor = "#7f9c96",
    rowLineColor = "rgba(255,255,255,0.12)",
    radius = 14,
    padding = 18,
    rampMode = "ramp",
    baseColor = "#4ED9B0",
    rampStrength = 0.72,
    colorOutright = "#4ED9B0",
    colorTb1 = "#3BA88A",
    colorTb2 = "#2C7A66",
    colorTb3 = "#1E5347",
    splitColor = "#E0A33E",
    barHeight = 72,
    barRadius = 10,
    segmentGap = 0,
    showDividers = true,
    dividerColor = "rgba(255,255,255,0.14)",
    minSegment = 4,
    reveal = "inView",
    revealAmount = 0.35,
    revealReplay = false,
    revealDuration = 700,
    revealStagger = 120,
    revealEasing = "easeOut",
    style,
}: Props) {
    useWebFont(FONT_URL, true)

    const auto = source === "auto"
    const fetched = useFetchedDeciding(auto, baseUrl, year, week)

    const [rootRef, shown, still] = useReveal(
        reveal,
        num(revealAmount, 0.35),
        !!revealReplay
    )
    const dur = Math.max(0, num(revealDuration, 700))
    const step = Math.max(0, num(revealStagger, 120))
    const ease = EASINGS[revealEasing] || EASINGS.easeOut

    const overrides: Record<LayerKey, string> = {
        outright: labelOutright,
        tb1: labelTb1,
        tb2: labelTb2,
        tb3: labelTb3,
        split: labelSplit,
    }

    const shares: Record<LayerKey, number> = auto
        ? (fetched.data?.shares as Record<LayerKey, number>) || {
              outright: 0,
              tb1: 0,
              tb2: 0,
              tb3: 0,
              split: 0,
          }
        : {
              outright: num(outright),
              tb1: num(tb1),
              tb2: num(tb2),
              tb3: num(tb3),
              split: num(split),
          }

    const deltas: Record<LayerKey, number | null> = auto
        ? (fetched.data?.deltas as Record<LayerKey, number | null>) || {
              outright: null,
              tb1: null,
              tb2: null,
              tb3: null,
              split: null,
          }
        : {
              outright: num(dOutright),
              tb1: num(dTb1),
              tb2: num(dTb2),
              tb3: num(dTb3),
              split: num(dSplit),
          }

    const totalOutcomes = auto
        ? (fetched.data?.outcomes ?? 0)
        : num(outcomes)

    const baseline = auto
        ? (fetched.data?.baselineWeek ?? null)
        : baselineWeek === null || baselineWeek === undefined
          ? null
          : num(baselineWeek)

    const segments = useMemo(
        () =>
            withMinimums(
                LAYERS.map((l) => ({ key: l.key, share: shares[l.key] })),
                num(minSegment, 4)
            ),
        [
            shares.outright,
            shares.tb1,
            shares.tb2,
            shares.tb3,
            shares.split,
            minSegment,
        ]
    )

    const sum =
        shares.outright + shares.tb1 + shares.tb2 + shares.tb3 + shares.split

    const [active, setActive] = useState<LayerKey | null>(null)

    const colorFor = (key: LayerKey): string => {
        if (key === "split") return splitColor
        if (rampMode === "custom") {
            return { outright: colorOutright, tb1: colorTb1, tb2: colorTb2, tb3: colorTb3 }[
                key
            ] as string
        }
        return baseColor
    }

    const opacityFor = (key: LayerKey, index: number): number => {
        if (key === "split") return 1
        if (rampMode === "custom") return 1
        return rampOpacity(index, num(rampStrength, 0.72))
    }

    /**
     * The top of the ramp is a near-solid fill and the bottom is nearly the
     * card, so one ink cannot serve both. Auto blends the fill over the surface
     * at that segment's opacity and picks by luminance, which is what makes a
     * dark palette and a bright one both work without touching this control.
     * Falls back to the opacity midpoint if a colour will not parse.
     */
    const labelInkFor = (key: LayerKey, index: number): string => {
        if (labelInkMode === "light") return ink
        if (labelInkMode === "dark") return labelInkDark
        const lum = effectiveLuminance(
            colorFor(key),
            opacityFor(key, index),
            surfaceColor
        )
        if (lum === null) return opacityFor(key, index) >= 0.55 ? labelInkDark : ink
        return lum > 0.42 ? labelInkDark : ink
    }

    const shortFor = (key: LayerKey): string => {
        const found = LAYERS.filter((l) => l.key === key)
        return found.length ? found[0].short : key
    }

    const labelFor = (key: LayerKey): string => {
        const custom = (overrides[key] || "").trim()
        if (custom) return custom
        const found = LAYERS.filter((l) => l.key === key)
        return found.length ? found[0].label : key
    }

    const shellStyle: any = {
        ...style,
        fontFamily: `"${fontFamily}", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`,
        fontSize: num(fontSize, 14),
        background,
        color: ink,
        borderRadius: num(radius, 14),
        padding: num(padding, 18),
    }

    // A notice rather than an empty frame, so a mis-set URL or a week without
    // the field reads as a setup problem instead of looking like real data.
    if (auto && (fetched.loading || fetched.error)) {
        return (
            <div className="fepdt" style={shellStyle}>
                <style>{CSS}</style>
                <div className="fepdt-notice" style={{ color: muted }}>
                    {fetched.loading ? "Loading the board..." : fetched.error}
                </div>
            </div>
        )
    }

    if (sum <= 0) {
        return (
            <div className="fepdt" style={shellStyle}>
                <style>{CSS}</style>
                <div className="fepdt-notice" style={{ color: muted }}>
                    No deciding layer for this week yet. Set the five shares, or
                    bind them to the week's CMS fields.
                </div>
            </div>
        )
    }

    const heading = (title || "").trim() || "Decision Tree"
    const eyebrowText =
        (eyebrow || "").trim() ||
        year + " | " + (num(week) === 0 ? "Preseason" : "Week " + num(week))
    const subtitleText = (subtitle || "").replace(
        /\{N\}/g,
        commas(totalOutcomes)
    )

    return (
        <div
            ref={rootRef}
            className="fepdt"
            style={shellStyle}
            role="img"
            aria-label={
                heading +
                ": " +
                LAYERS.filter((l) => shares[l.key] > 0)
                    .map((l) => labelFor(l.key) + " " + pct(shares[l.key]))
                    .join(", ")
            }
        >
            <style>{CSS}</style>

            {showEyebrow ? (
                <p className="fepdt-eyebrow" style={{ color: muted }}>
                    {eyebrowText}
                </p>
            ) : null}

            {showTitle ? <h3 className="fepdt-title">{heading}</h3> : null}

            {showSubtitle && subtitleText ? (
                <p className="fepdt-sub" style={{ color: muted }}>
                    {subtitleText}
                </p>
            ) : null}

            <div
                className="fepdt-bar"
                style={{
                    height: num(barHeight, 72),
                    borderRadius: num(barRadius, 10),
                    gap: num(segmentGap, 0),
                }}
                onMouseLeave={() => setActive(null)}
            >
                {segments.map((seg, i) => {
                    const index = LAYERS.findIndex((l) => l.key === seg.key)
                    const isSplit = seg.key === "split"
                    const color = colorFor(seg.key)
                    const gap = num(segmentGap, 0)
                    const outer = num(barRadius, 10)
                    // With gaps on, the container's overflow clip no longer
                    // shapes the ends, so the first and last segments carry the
                    // bar's own radius and the inner ones get a softer one.
                    const inner = Math.min(outer, num(barHeight, 72) / 2)
                    const corners =
                        gap > 0
                            ? {
                                  borderTopLeftRadius: i === 0 ? outer : inner,
                                  borderBottomLeftRadius: i === 0 ? outer : inner,
                                  borderTopRightRadius:
                                      i === segments.length - 1 ? outer : inner,
                                  borderBottomRightRadius:
                                      i === segments.length - 1 ? outer : inner,
                              }
                            : {}

                    // Each segment waits its turn, so the bar fills left to
                    // right and every layer gets a beat of its own.
                    const enter = i * step
                    const grow = still
                        ? undefined
                        : `width ${dur}ms ${ease} ${enter}ms`
                    // The text arrives once its segment has mostly landed.
                    const textIn = still
                        ? undefined
                        : `opacity ${Math.round(dur * 0.5)}ms ease-out ${Math.round(enter + dur * 0.55)}ms`

                    // Three tiers, so a segment degrades rather than
                    // truncating: full name, short name, number alone, empty.
                    const showText =
                        showInlineLabels && seg.width >= num(inlineLabelMin, 6)
                    const showName =
                        showText && seg.width >= num(inlineNameMin, 16)
                    const fullName =
                        !useShortNames &&
                        seg.width >= num(inlineFullNameMin, 30)

                    return (
                        <div
                            key={seg.key}
                            className="fepdt-seg"
                            data-dim={active && active !== seg.key ? "1" : "0"}
                            style={{
                                width: (shown ? seg.width : 0) + "%",
                                transition: [grow, "opacity .14s ease"]
                                    .filter(Boolean)
                                    .join(", "),
                                ...corners,
                            }}
                            onMouseEnter={() => setActive(seg.key)}
                            title={
                                labelFor(seg.key) +
                                " " +
                                pct(shares[seg.key]) +
                                (totalOutcomes
                                    ? " (" +
                                      commas(
                                          (shares[seg.key] / 100) * totalOutcomes
                                      ) +
                                      " of " +
                                      commas(totalOutcomes) +
                                      ")"
                                    : "")
                            }
                        >
                            <span
                                className="fepdt-fill"
                                style={{
                                    background: isSplit
                                        ? `repeating-linear-gradient(135deg, ${color} 0 6px, transparent 6px 12px)`
                                        : color,
                                    opacity: opacityFor(seg.key, index),
                                    boxShadow: isSplit
                                        ? `inset 0 0 0 1px ${color}`
                                        : "none",
                                }}
                            />
                            {showDividers && i > 0 && gap === 0 ? (
                                <span
                                    className="fepdt-divider"
                                    style={{ background: dividerColor }}
                                />
                            ) : null}
                            {showText ? (
                                <span
                                    className="fepdt-inner"
                                    data-layout={inlineLayout}
                                    style={{
                                        color: labelInkFor(seg.key, index),
                                        opacity: shown ? 1 : 0,
                                        transition: textIn,
                                    }}
                                >
                                    {showName ? (
                                        <span className="fepdt-segname">
                                            {fullName
                                                ? labelFor(seg.key)
                                                : shortFor(seg.key)}
                                        </span>
                                    ) : null}
                                    <span className="fepdt-segpct">
                                        {pct(shares[seg.key], 0)}
                                    </span>
                                </span>
                            ) : null}
                        </div>
                    )
                })}
            </div>

            {/* Always rendered. `data-wide="hidden"` drops it on wide frames
                only, because a narrow frame has no text inside the bar and a
                hidden legend there would leave the bar unlabelled. */}
            <div
                className="fepdt-legend"
                data-wide={showLegend ? "shown" : "hidden"}
            >
                {LAYERS.filter((l) => shares[l.key] > 0).map((layer, i) => {
                    const index = LAYERS.findIndex((l) => l.key === layer.key)
                    const delta = deltas[layer.key]
                    const enter = i * step
                    return (
                        <div
                            key={layer.key}
                            className="fepdt-row"
                            data-dim={active && active !== layer.key ? "1" : "0"}
                            style={{
                                borderTopColor: rowLineColor,
                                color: ink,
                                opacity: shown ? 1 : 0,
                                transform: shown ? "none" : "translateY(4px)",
                                transition: still
                                    ? undefined
                                    : `opacity ${Math.round(dur * 0.6)}ms ease-out ${Math.round(enter + dur * 0.4)}ms, transform ${Math.round(dur * 0.6)}ms ${ease} ${Math.round(enter + dur * 0.4)}ms`,
                            }}
                            onMouseEnter={() => setActive(layer.key)}
                            onMouseLeave={() => setActive(null)}
                        >
                            <span
                                className="fepdt-swatch"
                                style={{
                                    background: colorFor(layer.key),
                                    opacity: opacityFor(layer.key, index),
                                }}
                            />
                            <span className="fepdt-name">
                                {labelFor(layer.key)}
                            </span>
                            {showCounts && totalOutcomes ? (
                                <span
                                    className="fepdt-count"
                                    style={{ color: countColor }}
                                >
                                    {commas(
                                        (shares[layer.key] / 100) * totalOutcomes
                                    )}{" "}
                                    of {commas(totalOutcomes)}
                                </span>
                            ) : null}
                            <span className="fepdt-share">
                                {pct(shares[layer.key])}
                            </span>
                            {showDeltas ? (
                                <span
                                    className="fepdt-delta"
                                    style={{ color: muted }}
                                >
                                    {delta === null ? "" : signed(delta)}
                                </span>
                            ) : null}
                        </div>
                    )
                })}
            </div>

            {showDeltas && baseline !== null ? (
                <p className="fepdt-note" style={{ color: muted }}>
                    Change against Week {baseline}.
                </p>
            ) : null}
        </div>
    )
}

// ---------------------------------------------------------------------------
// property controls
// ---------------------------------------------------------------------------

addPropertyControls(FEPDecisionTree, {
    source: {
        type: ControlType.Enum,
        title: "Source",
        options: ["manual", "auto"],
        optionTitles: ["Manual / CMS", "Auto (JSON)"],
        defaultValue: "manual",
        description:
            "Manual takes the five shares from the properties below, so you " +
            "can bind them to CMS fields. Auto reads them out of the week file.",
    },
    year: {
        type: ControlType.Number,
        title: "Year",
        defaultValue: 2026,
        min: 2016,
        max: 2100,
        step: 1,
        displayStepper: true,
    },
    week: {
        type: ControlType.Number,
        title: "Week",
        defaultValue: 1,
        min: 0,
        max: 18,
        step: 1,
        displayStepper: true,
        description: "Bind to the newsletter's week. 0 is the preseason board.",
    },
    baseUrl: {
        type: ControlType.String,
        title: "Data base URL",
        defaultValue: "",
        placeholder: "https://raw.githubusercontent.com/.../chart-data",
        hidden: (p: any) => p.source !== "auto",
    },

    outright: {
        type: ControlType.Number,
        title: "Correct Picks",
        defaultValue: 62,
        min: 0,
        max: 100,
        step: 0.1,
        displayStepper: false,
        hidden: (p: any) => p.source === "auto",
    },
    tb1: {
        type: ControlType.Number,
        title: "TB1 Record",
        defaultValue: 16.6,
        min: 0,
        max: 100,
        step: 0.1,
        hidden: (p: any) => p.source === "auto",
    },
    tb2: {
        type: ControlType.Number,
        title: "TB2 Division",
        defaultValue: 9.1,
        min: 0,
        max: 100,
        step: 0.1,
        hidden: (p: any) => p.source === "auto",
    },
    tb3: {
        type: ControlType.Number,
        title: "TB3 Points",
        defaultValue: 12.4,
        min: 0,
        max: 100,
        step: 0.1,
        hidden: (p: any) => p.source === "auto",
    },
    split: {
        type: ControlType.Number,
        title: "Fully tied",
        defaultValue: 0,
        min: 0,
        max: 100,
        step: 0.1,
        description: "Leave at 0. It only appears when the cascade runs out.",
        hidden: (p: any) => p.source === "auto",
    },
    outcomes: {
        type: ControlType.Number,
        title: "Outcomes",
        defaultValue: 131072,
        min: 0,
        max: 200000,
        step: 1,
        description: "Remaining outcomes. Fills {N} in the subtitle and the counts.",
        hidden: (p: any) => p.source === "auto",
    },

    showDeltas: {
        type: ControlType.Boolean,
        title: "Deltas",
        defaultValue: false,
    },
    baselineWeek: {
        type: ControlType.Number,
        title: "vs Week",
        defaultValue: 0,
        min: 0,
        max: 18,
        step: 1,
        displayStepper: true,
        hidden: (p: any) => !p.showDeltas || p.source === "auto",
    },
    dOutright: {
        type: ControlType.Number,
        title: "Chg Picks",
        defaultValue: 0,
        min: -100,
        max: 100,
        step: 0.1,
        hidden: (p: any) => !p.showDeltas || p.source === "auto",
    },
    dTb1: {
        type: ControlType.Number,
        title: "Chg TB1",
        defaultValue: 0,
        min: -100,
        max: 100,
        step: 0.1,
        hidden: (p: any) => !p.showDeltas || p.source === "auto",
    },
    dTb2: {
        type: ControlType.Number,
        title: "Chg TB2",
        defaultValue: 0,
        min: -100,
        max: 100,
        step: 0.1,
        hidden: (p: any) => !p.showDeltas || p.source === "auto",
    },
    dTb3: {
        type: ControlType.Number,
        title: "Chg TB3",
        defaultValue: 0,
        min: -100,
        max: 100,
        step: 0.1,
        hidden: (p: any) => !p.showDeltas || p.source === "auto",
    },
    dSplit: {
        type: ControlType.Number,
        title: "Chg Tied",
        defaultValue: 0,
        min: -100,
        max: 100,
        step: 0.1,
        hidden: (p: any) => !p.showDeltas || p.source === "auto",
    },

    showEyebrow: {
        type: ControlType.Boolean,
        title: "Eyebrow",
        defaultValue: true,
    },
    eyebrow: {
        type: ControlType.String,
        title: "Custom eyebrow",
        placeholder: "2026 | Week 7",
        hidden: (p: any) => !p.showEyebrow,
    },
    showTitle: { type: ControlType.Boolean, title: "Title", defaultValue: true },
    title: {
        type: ControlType.String,
        title: "Custom title",
        defaultValue: "Decision Tree",
        hidden: (p: any) => !p.showTitle,
    },
    showSubtitle: {
        type: ControlType.Boolean,
        title: "Subtitle",
        defaultValue: true,
    },
    subtitle: {
        type: ControlType.String,
        title: "Subtitle text",
        defaultValue:
            "All {N} ways this season can still end, sorted by what actually decides them.",
        displayTextArea: true,
        description: "{N} is replaced with the remaining outcome count.",
        hidden: (p: any) => !p.showSubtitle,
    },
    showLegend: {
        type: ControlType.Boolean,
        title: "Legend",
        defaultValue: true,
    },
    showCounts: {
        type: ControlType.Boolean,
        title: "Outcome counts",
        defaultValue: true,
        description: "108 of 256 futures, beside each share.",
        hidden: (p: any) => !p.showLegend,
    },
    showInlineLabels: {
        type: ControlType.Boolean,
        title: "Text in bar",
        defaultValue: true,
        description:
            "Always pulled out below 520px, where the legend carries it instead.",
    },
    inlineLayout: {
        type: ControlType.Enum,
        title: "Text layout",
        options: ["stacked", "inline"],
        optionTitles: ["Name over number", "Side by side"],
        defaultValue: "stacked",
        hidden: (p: any) => !p.showInlineLabels,
    },
    useShortNames: {
        type: ControlType.Boolean,
        title: "Always short",
        defaultValue: false,
        description:
            "Picks, TB1, TB2, TB3, Tied everywhere, instead of only on the " +
            "segments too narrow for the full name.",
        hidden: (p: any) => !p.showInlineLabels,
    },
    inlineFullNameMin: {
        type: ControlType.Number,
        title: "Full name above",
        defaultValue: 30,
        min: 5,
        max: 80,
        step: 1,
        unit: "%",
        description:
            "Narrower than this and the segment uses the short name instead " +
            "of truncating the long one.",
        hidden: (p: any) => !p.showInlineLabels || p.useShortNames,
    },
    inlineNameMin: {
        type: ControlType.Number,
        title: "Short name above",
        defaultValue: 16,
        min: 5,
        max: 60,
        step: 1,
        unit: "%",
        description: "Narrower than this and the segment shows only its number.",
        hidden: (p: any) => !p.showInlineLabels,
    },
    inlineLabelMin: {
        type: ControlType.Number,
        title: "Number above",
        defaultValue: 6,
        min: 0,
        max: 40,
        step: 1,
        unit: "%",
        description: "Narrower than this and the segment stays empty.",
        hidden: (p: any) => !p.showInlineLabels,
    },

    labelInkMode: {
        type: ControlType.Enum,
        title: "Label ink",
        options: ["auto", "light", "dark"],
        optionTitles: ["Auto", "Always light", "Always dark"],
        defaultValue: "auto",
        description:
            "Auto puts dark text on the solid segments and light text on the " +
            "faded ones, which is the only way one setting reads on both.",
        hidden: (p: any) => !p.showInlineLabels,
    },
    labelInkDark: {
        type: ControlType.Color,
        title: "Label dark",
        defaultValue: "#06231f",
        hidden: (p: any) => !p.showInlineLabels || p.labelInkMode === "light",
    },
    surfaceColor: {
        type: ControlType.Color,
        title: "Behind bar",
        defaultValue: "#06231f",
        description:
            "The colour under the bar. Auto ink blends each fill over this to " +
            "work out whether light or dark text reads. Only used for that.",
        hidden: (p: any) =>
            !p.showInlineLabels || p.labelInkMode !== "auto",
    },

    fontFamily: {
        type: ControlType.String,
        title: "Font",
        defaultValue: "Maven Pro",
    },
    fontSize: {
        type: ControlType.Number,
        title: "Base size",
        defaultValue: 14,
        min: 10,
        max: 24,
        step: 1,
        unit: "px",
        description: "Everything scales off this.",
    },
    background: {
        type: ControlType.String,
        title: "Background",
        defaultValue: "linear-gradient(160deg,#04302a,#06231f)",
    },
    ink: { type: ControlType.Color, title: "Text", defaultValue: "#eafaf6" },
    muted: { type: ControlType.Color, title: "Muted", defaultValue: "#7f9c96" },
    countColor: {
        type: ControlType.Color,
        title: "Count",
        defaultValue: "#7f9c96",
        description: "The \"108 of 256\" text in the legend.",
        hidden: (p: any) => !p.showLegend || !p.showCounts,
    },
    rowLineColor: {
        type: ControlType.Color,
        title: "Row line",
        defaultValue: "rgba(255,255,255,0.12)",
        description:
            "The hairline between legend rows. Separate from Divider, which " +
            "is the line inside the bar.",
        hidden: (p: any) => !p.showLegend,
    },
    radius: {
        type: ControlType.Number,
        title: "Corner",
        defaultValue: 14,
        min: 0,
        max: 48,
        step: 1,
        unit: "px",
    },
    padding: {
        type: ControlType.Number,
        title: "Padding",
        defaultValue: 18,
        min: 0,
        max: 64,
        step: 1,
        unit: "px",
    },

    rampMode: {
        type: ControlType.Enum,
        title: "Colours",
        options: ["ramp", "custom"],
        optionTitles: ["One hue, fading", "One per layer"],
        defaultValue: "ramp",
        description:
            "The cascade reads best as one colour getting fainter: depth on " +
            "screen for depth in the tiebreakers.",
    },
    baseColor: {
        type: ControlType.Color,
        title: "Base",
        defaultValue: "#4ED9B0",
        hidden: (p: any) => p.rampMode !== "ramp",
    },
    rampStrength: {
        type: ControlType.Number,
        title: "Falloff",
        defaultValue: 0.72,
        min: 0.3,
        max: 0.95,
        step: 0.01,
        description: "Lower fades faster.",
        hidden: (p: any) => p.rampMode !== "ramp",
    },
    colorOutright: {
        type: ControlType.Color,
        title: "Picks",
        defaultValue: "#4ED9B0",
        hidden: (p: any) => p.rampMode !== "custom",
    },
    colorTb1: {
        type: ControlType.Color,
        title: "TB1",
        defaultValue: "#3BA88A",
        hidden: (p: any) => p.rampMode !== "custom",
    },
    colorTb2: {
        type: ControlType.Color,
        title: "TB2",
        defaultValue: "#2C7A66",
        hidden: (p: any) => p.rampMode !== "custom",
    },
    colorTb3: {
        type: ControlType.Color,
        title: "TB3",
        defaultValue: "#1E5347",
        hidden: (p: any) => p.rampMode !== "custom",
    },
    splitColor: {
        type: ControlType.Color,
        title: "Fully tied",
        defaultValue: "#E0A33E",
        description: "Breaks the ramp on purpose. It is not the next rung.",
    },

    barHeight: {
        type: ControlType.Number,
        title: "Bar height",
        defaultValue: 72,
        min: 8,
        max: 96,
        step: 1,
        unit: "px",
    },
    barRadius: {
        type: ControlType.Number,
        title: "Bar corner",
        defaultValue: 10,
        min: 0,
        max: 48,
        step: 1,
        unit: "px",
    },
    segmentGap: {
        type: ControlType.Number,
        title: "Segment gap",
        defaultValue: 0,
        min: 0,
        max: 12,
        step: 1,
        unit: "px",
    },
    showDividers: {
        type: ControlType.Boolean,
        title: "Dividers",
        defaultValue: true,
        description:
            "A hairline between segments. Only drawn when the gap is 0, where " +
            "two neighbouring rungs of the ramp can otherwise read as one.",
    },
    dividerColor: {
        type: ControlType.Color,
        title: "Divider",
        defaultValue: "rgba(255,255,255,0.14)",
        hidden: (p: any) => !p.showDividers,
    },
    minSegment: {
        type: ControlType.Number,
        title: "Min segment",
        defaultValue: 4,
        min: 0,
        max: 15,
        step: 0.5,
        unit: "%",
        description:
            "Floor so a 2.7% tiebreaker stays visible. The difference comes " +
            "off the widest segments, and the bar still sums to 100.",
    },

    reveal: {
        type: ControlType.Enum,
        title: "Reveal",
        options: ["inView", "onLoad", "off"],
        optionTitles: ["When scrolled into view", "On page load", "Off"],
        defaultValue: "inView",
        description:
            "Segments grow one after another, so the bar fills left to right " +
            "and each layer gets its own beat.",
    },
    revealAmount: {
        type: ControlType.Number,
        title: "Fires at",
        defaultValue: 0.35,
        min: 0,
        max: 1,
        step: 0.05,
        description:
            "How much of the bar has to be on screen. It also fires once the " +
            "bar clears the bottom 15% of the viewport, so a tall bar on a " +
            "short screen cannot get stuck waiting.",
        hidden: (p: any) => p.reveal !== "inView",
    },
    revealReplay: {
        type: ControlType.Boolean,
        title: "Replay",
        defaultValue: false,
        description: "Run it again every time it comes back into view.",
        hidden: (p: any) => p.reveal !== "inView",
    },
    revealDuration: {
        type: ControlType.Number,
        title: "Duration",
        defaultValue: 700,
        min: 0,
        max: 3000,
        step: 50,
        unit: "ms",
        description: "How long one segment takes to grow.",
        hidden: (p: any) => p.reveal === "off",
    },
    revealStagger: {
        type: ControlType.Number,
        title: "Stagger",
        defaultValue: 120,
        min: 0,
        max: 1200,
        step: 10,
        unit: "ms",
        description:
            "The gap between one segment starting and the next. 0 grows them " +
            "all at once.",
        hidden: (p: any) => p.reveal === "off",
    },
    revealEasing: {
        type: ControlType.Enum,
        title: "Easing",
        options: ["easeOut", "easeInOut", "overshoot", "linear"],
        optionTitles: ["Ease out", "Ease in out", "Overshoot", "Linear"],
        defaultValue: "easeOut",
        hidden: (p: any) => p.reveal === "off",
    },

    labelOutright: {
        type: ControlType.String,
        title: "Name: Picks",
        placeholder: "Correct Picks",
    },
    labelTb1: {
        type: ControlType.String,
        title: "Name: TB1",
        placeholder: "Tiebreaker 1 - Season Record",
    },
    labelTb2: {
        type: ControlType.String,
        title: "Name: TB2",
        placeholder: "Tiebreaker 2 - Division Record",
    },
    labelTb3: {
        type: ControlType.String,
        title: "Name: TB3",
        placeholder: "Tiebreaker 3 - Points Total",
    },
    labelSplit: {
        type: ControlType.String,
        title: "Name: Tied",
        placeholder: "Fully tied (even split)",
    },
})
