import { addPropertyControls, ControlType, RenderTarget } from "framer"
import { useEffect, useMemo, useRef, useState } from "react"

/**
 * FEP Leverage Spine
 * ==================
 *
 * Every game of the season on one axis, each bar as tall as that game's
 * leverage: the share of total leaderboard equity riding on the result.
 *
 * The weekly Leverage Index number ("54.7% swings on this one result") is
 * abstract on its own. The spine is the season-long version of it, and it is
 * the only FEP visual that gets better every week: you watch the leverage drain
 * out of the schedule and pool into the last three games.
 *
 * Played and unplayed bars are not the same quantity, and the component does
 * not pretend otherwise. A played bar is retrospective, how much that result
 * actually moved the board. An unplayed bar is prospective, how much it could.
 * They share an axis because they answer the same question in the same units,
 * but the fill tells you which is which, and `Mixed units note` exists so you
 * can say so in the newsletter.
 *
 * Everything is a property
 * ------------------------
 * Values arrive as comma-separated strings so a single CMS text field can drive
 * the whole row. Three fields, one per series:
 *
 *   Labels      "vs Commanders, @ Chiefs, vs Giants, ..."
 *   Leverage    "12.1, 8.4, 19.0, ..."
 *   Results     "W, L, , , ..."          blank means not played yet
 *
 * Lists of unequal length are padded rather than refused, because a half-filled
 * CMS row should render what it has instead of showing nothing.
 *
 * Mobile
 * ------
 * The bars always fit, no horizontal scroll, because the shape of the season is
 * the point and a shape you have to scroll is not a shape. The labelling gives
 * way instead: full labels, then short ones, then the result strip alone.
 *
 * House rule: no em dashes and no en dashes in any string this renders.
 */

const FONT_URL =
    "https://fonts.googleapis.com/css2?family=Maven+Pro:wght@400;500;600;700;800&display=swap"

type Game = {
    index: number
    label: string
    short: string
    value: number
    result: string
    isNext: boolean
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function useWebFont(href: string) {
    useEffect(() => {
        if (typeof document === "undefined") return
        if (document.querySelector('link[data-fep-font="maven-pro"]')) return
        const link = document.createElement("link")
        link.rel = "stylesheet"
        link.href = href
        link.setAttribute("data-fep-font", "maven-pro")
        document.head.appendChild(link)
    }, [href])
}

function num(value: unknown, fallback = 0): number {
    const n = typeof value === "string" ? parseFloat(value) : (value as number)
    return typeof n === "number" && isFinite(n) ? n : fallback
}

function splitList(text: string, separator: string): string[] {
    if (!text) return []
    return text.split(separator || ",").map((part) => part.trim())
}

/**
 * ESPN's scoreboard abbreviations, mirroring fep/teams.py.
 *
 * The sheet is the source of truth and normally supplies these, so this is
 * the fallback for an unbound instance. It is a real table rather than a rule
 * because the rule does not work: first-three-letters gives COM for the
 * Commanders, STE for the Steelers and 49E for the 49ers, and none of those
 * is what a scoreboard says.
 */
const ABBR: Record<string, string> = {
    "49ers": "SF", Bears: "CHI", Bengals: "CIN", Bills: "BUF",
    Broncos: "DEN", Browns: "CLE", Buccaneers: "TB", Cardinals: "ARI",
    Chargers: "LAC", Chiefs: "KC", Colts: "IND", Commanders: "WSH",
    Cowboys: "DAL", Dolphins: "MIA", Eagles: "PHI", Falcons: "ATL",
    Giants: "NYG", Jaguars: "JAX", Jets: "NYJ", Lions: "DET",
    Packers: "GB", Panthers: "CAR", Patriots: "NE", Raiders: "LV",
    Rams: "LAR", Ravens: "BAL", Saints: "NO", Seahawks: "SEA",
    Steelers: "PIT", Texans: "HOU", Titans: "TEN", Vikings: "MIN",
}

/** "vs. Jaguars (London)" becomes "JAX". */
function deriveShort(label: string): string {
    // Drop a parenthetical first: the London game is a Jaguars game played
    // elsewhere, and the venue is not part of the team's name.
    const bare = (label || "").replace(/\([^)]*\)/g, " ")
    const name = bare.replace(/^\s*(vs\.?|@|at)\s*/i, "").trim()
    if (ABBR[name]) return ABBR[name]
    const words = name.split(/\s+/)
    const last = words.length ? words[words.length - 1] : name
    return (ABBR[last] || last.slice(0, 3)).toUpperCase()
}

const EASINGS: Record<string, string> = {
    easeOut: "cubic-bezier(0.22, 1, 0.36, 1)",
    easeInOut: "cubic-bezier(0.65, 0, 0.35, 1)",
    overshoot: "cubic-bezier(0.34, 1.56, 0.64, 1)",
    linear: "linear",
}

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

function useFetchedSpine(
    enabled: boolean,
    baseUrl: string,
    year: number,
    week: number
) {
    const [state, setState] = useState<{
        games: Game[] | null
        error: string | null
        loading: boolean
    }>({ games: null, error: null, loading: false })

    useEffect(() => {
        if (!enabled) {
            setState({ games: null, error: null, loading: false })
            return
        }
        if (!baseUrl) {
            setState({ games: null, error: "Set the data base URL.", loading: false })
            return
        }
        const root = baseUrl.replace(/\/+$/, "")
        const withYear = new RegExp("/" + year + "$").test(root)
            ? root
            : root + "/" + year
        const url = withYear + "/week-" + String(week).padStart(2, "0") + ".json"

        let cancelled = false
        setState({ games: null, error: null, loading: true })

        fetch(url)
            .then((r) => {
                if (!r.ok) throw new Error("HTTP " + r.status)
                return r.json()
            })
            .then((payload: any) => {
                if (cancelled) return
                const rows = payload && payload.leverage
                if (!Array.isArray(rows)) {
                    // Silent, not an error: an older week file predates the
                    // field and a newsletter page should not shout about it.
                    setState({ games: null, error: null, loading: false })
                    return
                }
                let seenBlank = false
                const games: Game[] = rows.map((row: any, i: number) => {
                    const result = String(row.result || "").toUpperCase()
                    const isNext = !result && !seenBlank
                    if (!result) seenBlank = true
                    return {
                        index: i,
                        label: String(row.label || ""),
                        short: String(row.short || deriveShort(String(row.label || ""))),
                        value: num(row.leverage),
                        result,
                        isNext,
                    }
                })
                setState({ games, error: null, loading: false })
            })
            .catch((e) => {
                if (!cancelled) {
                    setState({
                        games: null,
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
.fepls{container-type:inline-size;box-sizing:border-box}
.fepls *{box-sizing:border-box}
.fepls-eyebrow{font-size:.78em;font-weight:700;letter-spacing:.09em;
  text-transform:uppercase;margin:0 0 6px}
.fepls-title{font-size:1.5em;font-weight:800;letter-spacing:-.01em;margin:0}
.fepls-sub{font-size:.95em;line-height:1.45;margin:6px 0 0;max-width:62ch}
.fepls-caption{font-size:.72em;font-weight:700;letter-spacing:.05em;
  margin:18px 0 0;line-height:1.35}
.fepls-plot{display:flex;align-items:flex-end;width:100%;margin-top:8px;
  position:relative}
.fepls-col{flex:1 1 0;min-width:0;display:flex;flex-direction:column;
  align-items:center;justify-content:flex-end;position:relative;
  transition:opacity .14s ease;cursor:default}
.fepls-col[data-dim="1"]{opacity:.3}
.fepls-val{font-size:.68em;font-weight:800;font-variant-numeric:tabular-nums;
  line-height:1;margin-bottom:4px;white-space:nowrap}
.fepls-barwrap{width:100%;display:flex;justify-content:center;align-items:flex-end}
/* Bars are sized in pixels, not percentages. A percentage height inside an
   auto-height flex wrapper has no definite parent to resolve against, and
   every bar silently collapses to nothing. */
.fepls-bar{width:100%;transform-origin:bottom center;flex:none}
.fepls-baseline{height:1px;width:100%;margin-top:0}
.fepls-strip{display:flex;width:100%;margin-top:7px}
.fepls-cell{flex:1 1 0;min-width:0;display:flex;justify-content:center}
.fepls-res{font-size:.66em;font-weight:800;letter-spacing:.04em;line-height:1.6}
.fepls-names{display:flex;width:100%;margin-top:5px}
.fepls-name{flex:1 1 0;min-width:0;font-size:.62em;font-weight:600;
  text-align:center;line-height:1.25;overflow:hidden;padding:0 1px;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.fepls-foot{font-size:.88em;line-height:1.5;margin:14px 0 0;max-width:62ch}
.fepls-note{font-size:.78em;line-height:1.5;margin:8px 0 0;max-width:62ch}
.fepls-key{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px;
  font-size:.74em;font-weight:600}
.fepls-keyitem{display:inline-flex;align-items:center;gap:6px}
.fepls-keydot{width:9px;height:9px;border-radius:2px;flex:none}
.fepls-notice{display:flex;align-items:center;justify-content:center;
  min-height:110px;text-align:center;font-size:.92em;line-height:1.5;
  opacity:.85;padding:16px}

@container (max-width: 620px){
  /* Only the every-bar mode is too dense to survive here. Two or three called
     out on purpose still fit, and they are the ones carrying the unit. */
  .fepls-plot[data-vmode="all"] .fepls-val{display:none}
  .fepls-title{font-size:1.28em}
}
/* Seventeen full game labels need far more room than seventeen bars do, so the
   label tier switches much later than the value tier. Below this they are
   abbreviations, which is the form that actually reads. */
@container (max-width: 900px){
  .fepls-name[data-tier="full"]{display:none}
}
@container (min-width: 901px){
  .fepls-name[data-tier="short"]{display:none}
}
@container (max-width: 380px){
  .fepls-names{display:none}
}
@media (prefers-reduced-motion: reduce){
  .fepls-bar,.fepls-col{transition:none !important}
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
    labels?: string
    leverages?: string
    results?: string
    shortLabels?: string
    separator?: string
    nextGame?: number
    showEyebrow?: boolean
    eyebrow?: string
    showTitle?: boolean
    title?: string
    showSubtitle?: boolean
    subtitle?: string
    showFoot?: boolean
    foot?: string
    showNote?: boolean
    note?: string
    showKey?: boolean
    keyRemaining?: string
    keyNext?: string
    keyWin?: string
    keyLoss?: string
    emptyText?: string
    valueMode?: "all" | "notable" | "none"
    valueSuffix?: string
    valueDecimals?: number
    showAxisCaption?: boolean
    axisCaption?: string
    showStrip?: boolean
    showNames?: boolean
    winMark?: string
    lossMark?: string
    tieMark?: string
    pendingMark?: string
    fontFamily?: string
    fontSize?: number
    background?: string
    ink?: string
    muted?: string
    radius?: number
    padding?: number
    plotHeight?: number
    barGap?: number
    barRadius?: number
    barWidth?: number
    scaleMode?: "auto" | "fixed"
    scaleMax?: number
    remainingColor?: string
    nextColor?: string
    winColor?: string
    lossColor?: string
    tieColor?: string
    playedOpacity?: number
    baselineColor?: string
    nextOutline?: boolean
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
 * @framerSupportedLayoutWidth any
 * @framerSupportedLayoutHeight auto
 * @framerIntrinsicWidth 720
 * @framerIntrinsicHeight 340
 */
export default function FEPLeverageSpine({
    source = "manual",
    year = 2026,
    week = 1,
    baseUrl = "",
    labels = "vs Commanders, @ Chiefs, vs Rams, @ Buccaneers, vs Broncos, @ Giants, vs Cowboys, @ Commanders, vs Packers, @ Cowboys, vs Bears, @ Chargers, vs Raiders, @ Bills, vs Lions, @ Jaguars, vs Giants",
    leverages = "9.1, 7.4, 11.2, 8.8, 10.4, 14.7, 19.3, 16.1, 12.6, 21.8, 13.9, 17.2, 11.5, 24.6, 22.1, 18.4, 26.3",
    results = "W, L, W, , , , , , , , , , , , , , ",
    shortLabels = "WSH, TEN, CHI, LAR, JAX, CAR, DAL, WSH, NYG, PIT, DAL, ARI, IND, SEA, HOU, SF, NYG",
    separator = ",",
    nextGame = 0,
    showEyebrow = true,
    eyebrow = "",
    showTitle = true,
    title = "Leverage Index",
    showSubtitle = true,
    subtitle = "Every game of the season, as tall as the share of the leaderboard riding on it.",
    showFoot = true,
    foot = "{topLabel} carries the most leverage left, at {topValue}.",
    showNote = false,
    note = "Played games show what the result actually moved. Unplayed games show what it could.",
    showKey = true,
    keyRemaining = "Still to play",
    keyNext = "Next up",
    keyWin = "Won",
    keyLoss = "Lost",
    emptyText = "No leverage for this week yet.",
    valueMode = "notable",
    valueSuffix = "%",
    valueDecimals = 0,
    showAxisCaption = true,
    axisCaption = "Share of the whole leaderboard that swings on each result",
    showStrip = true,
    showNames = true,
    winMark = "W",
    lossMark = "L",
    tieMark = "T",
    pendingMark = "",
    fontFamily = "Maven Pro",
    fontSize = 14,
    background = "linear-gradient(160deg,#04302a,#06231f)",
    ink = "#eafaf6",
    muted = "#7f9c96",
    radius = 14,
    padding = 18,
    plotHeight = 180,
    barGap = 4,
    barRadius = 4,
    barWidth = 100,
    scaleMode = "auto",
    scaleMax = 100,
    remainingColor = "#4ED9B0",
    nextColor = "#F2C14E",
    winColor = "#2C7A66",
    lossColor = "#8C3B3B",
    tieColor = "#5A6B68",
    playedOpacity = 0.85,
    baselineColor = "rgba(255,255,255,0.16)",
    nextOutline = true,
    reveal = "inView",
    revealAmount = 0.35,
    revealReplay = false,
    revealDuration = 700,
    revealStagger = 45,
    revealEasing = "easeOut",
    style,
}: Props) {
    useWebFont(FONT_URL)

    const auto = source === "auto"
    const fetched = useFetchedSpine(auto, baseUrl, year, week)
    const [rootRef, shown, still] = useReveal(
        reveal,
        num(revealAmount, 0.35),
        !!revealReplay
    )
    const dur = Math.max(0, num(revealDuration, 700))
    const step = Math.max(0, num(revealStagger, 45))
    const ease = EASINGS[revealEasing] || EASINGS.easeOut

    const games: Game[] = useMemo(() => {
        if (auto) return fetched.games || []

        const labelList = splitList(labels, separator)
        const valueList = splitList(leverages, separator)
        const resultList = splitList(results, separator)
        const shortList = splitList(shortLabels, separator)

        // Pad rather than refuse: a half-filled CMS row should render what it
        // has, not nothing at all.
        const count = Math.max(labelList.length, valueList.length)
        if (!count) return []

        const pinned = Math.round(num(nextGame, 0))
        let firstBlank = -1
        for (let i = 0; i < count; i++) {
            if (!(resultList[i] || "").trim()) {
                firstBlank = i
                break
            }
        }
        const nextIndex = pinned > 0 ? pinned - 1 : firstBlank

        const out: Game[] = []
        for (let i = 0; i < count; i++) {
            const label = labelList[i] || ""
            out.push({
                index: i,
                label,
                short: (shortList[i] || "").trim() || deriveShort(label),
                value: num(valueList[i]),
                result: (resultList[i] || "").trim().toUpperCase(),
                isNext: i === nextIndex,
            })
        }
        return out
    }, [
        auto,
        fetched.games,
        labels,
        leverages,
        results,
        shortLabels,
        separator,
        nextGame,
    ])

    const [active, setActive] = useState<number | null>(null)

    const shellStyle: any = {
        ...style,
        fontFamily: `"${fontFamily}", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`,
        fontSize: num(fontSize, 14),
        background,
        color: ink,
        borderRadius: num(radius, 14),
        padding: num(padding, 18),
    }

    if (auto && (fetched.loading || fetched.error)) {
        return (
            <div className="fepls" style={shellStyle}>
                <style>{CSS}</style>
                <div className="fepls-notice" style={{ color: muted }}>
                    {fetched.loading ? "Loading the board..." : fetched.error}
                </div>
            </div>
        )
    }

    if (!games.length) {
        return (
            <div className="fepls" style={shellStyle}>
                <style>{CSS}</style>
                <div className="fepls-notice" style={{ color: muted }}>
                    {emptyText}
                </div>
            </div>
        )
    }

    const peak = games.reduce((top, g) => Math.max(top, g.value), 0)
    const ceiling =
        scaleMode === "fixed"
            ? Math.max(1, num(scaleMax, 100))
            : Math.max(1, peak)
    // The value labels sit above the bars inside the same box, so the tallest
    // bar gets the plot height minus the room they take.
    const usable = Math.max(
        10,
        num(plotHeight, 180) -
            (valueMode === "none" ? 0 : Math.round(num(fontSize, 14) * 1.2))
    )

    // The tallest bar of the games still to play, which is what the footnote
    // talks about. Falls back to the tallest overall when nothing is left.
    const remaining = games.filter((g) => !g.result)
    const top = (remaining.length ? remaining : games).reduce(
        (best, g) => (g.value > best.value ? g : best),
        (remaining.length ? remaining : games)[0]
    )
    const next = games.filter((g) => g.isNext)[0]

    // Labelling every bar buries the shape the chart exists to show, and a
    // wall of bare digits is what makes it read as noise. "Notable" calls out
    // the two that the footnote is about, and those carry the unit for the
    // rest of the axis.
    const notable = new Set<number>()
    if (next) notable.add(next.index)
    if (top) notable.add(top.index)

    const labelled = (g: Game): boolean =>
        valueMode === "all" ? true : valueMode === "notable" ? notable.has(g.index) : false

    const valueText = (g: Game): string =>
        g.value.toFixed(Math.max(0, Math.min(2, Math.round(num(valueDecimals, 0))))) +
        (valueSuffix || "")

    const fill = (g: Game): string => {
        if (g.result === "W") return winColor
        if (g.result === "L") return lossColor
        if (g.result === "T") return tieColor
        return g.isNext ? nextColor : remainingColor
    }

    const markFor = (g: Game): string => {
        if (g.result === "W") return winMark
        if (g.result === "L") return lossMark
        if (g.result === "T") return tieMark
        return pendingMark
    }

    const token = (text: string): string =>
        (text || "")
            .replace(/\{topLabel\}/g, top ? top.label : "")
            .replace(/\{topValue\}/g, top ? top.value.toFixed(1) + "%" : "")
            .replace(/\{nextLabel\}/g, next ? next.label : "")
            .replace(/\{nextValue\}/g, next ? next.value.toFixed(1) + "%" : "")
            .replace(/\{played\}/g, String(games.filter((g) => g.result).length))
            .replace(/\{remaining\}/g, String(remaining.length))
            .replace(/\{week\}/g, String(num(week)))
            .replace(/\{year\}/g, String(num(year)))

    const eyebrowText =
        (eyebrow || "").trim() ||
        year + " | " + (num(week) === 0 ? "Preseason" : "Week " + num(week))

    const keyItems = [
        { on: true, color: remainingColor, label: keyRemaining },
        { on: !!next, color: nextColor, label: keyNext },
        { on: games.some((g) => g.result === "W"), color: winColor, label: keyWin },
        { on: games.some((g) => g.result === "L"), color: lossColor, label: keyLoss },
    ].filter((item) => item.on && (item.label || "").trim())

    return (
        <div
            ref={rootRef}
            className="fepls"
            style={shellStyle}
            role="img"
            aria-label={
                (title || "Leverage Index") +
                ": " +
                games
                    .map((g) => g.label + " " + g.value.toFixed(1) + "%")
                    .join(", ")
            }
        >
            <style>{CSS}</style>

            {showEyebrow ? (
                <p className="fepls-eyebrow" style={{ color: muted }}>
                    {eyebrowText}
                </p>
            ) : null}
            {showTitle ? <h3 className="fepls-title">{token(title)}</h3> : null}
            {showSubtitle && subtitle ? (
                <p className="fepls-sub" style={{ color: muted }}>
                    {token(subtitle)}
                </p>
            ) : null}

            {showAxisCaption && axisCaption ? (
                <p className="fepls-caption" style={{ color: muted }}>
                    {token(axisCaption)}
                </p>
            ) : null}

            <div
                className="fepls-plot"
                data-vmode={valueMode}
                style={{ height: num(plotHeight, 180), gap: num(barGap, 4) }}
                onMouseLeave={() => setActive(null)}
            >
                {games.map((g) => {
                    const height = Math.max(
                        0,
                        Math.min(usable, (g.value / ceiling) * usable)
                    )
                    const enter = g.index * step
                    const played = !!g.result
                    return (
                        <div
                            key={g.index}
                            className="fepls-col"
                            data-dim={
                                active !== null && active !== g.index ? "1" : "0"
                            }
                            onMouseEnter={() => setActive(g.index)}
                            title={
                                g.label +
                                ": " +
                                g.value.toFixed(1) +
                                "%" +
                                (played ? " (played, " + g.result + ")" : "")
                            }
                        >
                            {labelled(g) ? (
                                <span
                                    className="fepls-val"
                                    style={{
                                        color: played
                                            ? muted
                                            : g.isNext
                                              ? nextColor
                                              : ink,
                                        opacity: shown ? 1 : 0,
                                        transition: still
                                            ? undefined
                                            : `opacity ${Math.round(dur * 0.5)}ms ease-out ${Math.round(enter + dur * 0.5)}ms`,
                                    }}
                                >
                                    {valueText(g)}
                                </span>
                            ) : null}

                            <span className="fepls-barwrap">
                                <span
                                    className="fepls-bar"
                                    style={{
                                        width: Math.max(
                                            4,
                                            Math.min(100, num(barWidth, 100))
                                        ) + "%",
                                        // Scaling rather than animating height
                                        // keeps the whole row on the compositor.
                                        height: Math.round(height),
                                        minHeight: g.value > 0 ? 2 : 0,
                                        background: fill(g),
                                        opacity: played
                                            ? Math.max(0, Math.min(1, num(playedOpacity, 0.85)))
                                            : 1,
                                        // Top corners only. A bar sits on the
                                        // baseline, so rounding its bottom
                                        // lifts it off the axis it is measured
                                        // against.
                                        borderTopLeftRadius: num(barRadius, 4),
                                        borderTopRightRadius: num(barRadius, 4),
                                        borderBottomLeftRadius: 0,
                                        borderBottomRightRadius: 0,
                                        boxShadow:
                                            nextOutline && g.isNext
                                                ? `0 0 0 2px ${nextColor}66`
                                                : "none",
                                        transform: shown
                                            ? "scaleY(1)"
                                            : "scaleY(0)",
                                        transition: still
                                            ? undefined
                                            : `transform ${dur}ms ${ease} ${enter}ms`,
                                    }}
                                />
                            </span>
                        </div>
                    )
                })}
            </div>

            <div
                className="fepls-baseline"
                style={{ background: baselineColor }}
            />

            {showStrip ? (
                <div className="fepls-strip" style={{ gap: num(barGap, 4) }}>
                    {games.map((g) => (
                        <span key={g.index} className="fepls-cell">
                            <span
                                className="fepls-res"
                                style={{
                                    color:
                                        g.result === "W"
                                            ? winColor
                                            : g.result === "L"
                                              ? lossColor
                                              : g.isNext
                                                ? nextColor
                                                : muted,
                                    opacity: shown ? 1 : 0,
                                    transition: still
                                        ? undefined
                                        : `opacity ${Math.round(dur * 0.5)}ms ease-out ${Math.round(g.index * step + dur * 0.4)}ms`,
                                }}
                            >
                                {markFor(g)}
                            </span>
                        </span>
                    ))}
                </div>
            ) : null}

            {showNames ? (
                <div className="fepls-names" style={{ gap: num(barGap, 4) }}>
                    {games.map((g) => (
                        <span
                            key={g.index}
                            className="fepls-name"
                            data-tier="full"
                            style={{ color: g.isNext ? ink : muted }}
                        >
                            {g.label}
                        </span>
                    ))}
                    {games.map((g) => (
                        <span
                            key={"s" + g.index}
                            className="fepls-name"
                            data-tier="short"
                            style={{ color: g.isNext ? ink : muted }}
                        >
                            {g.short}
                        </span>
                    ))}
                </div>
            ) : null}

            {showKey && keyItems.length ? (
                <div className="fepls-key" style={{ color: muted }}>
                    {keyItems.map((item) => (
                        <span key={item.label} className="fepls-keyitem">
                            <span
                                className="fepls-keydot"
                                style={{ background: item.color }}
                            />
                            {item.label}
                        </span>
                    ))}
                </div>
            ) : null}

            {showFoot && foot ? (
                <p className="fepls-foot">{token(foot)}</p>
            ) : null}
            {showNote && note ? (
                <p className="fepls-note" style={{ color: muted }}>
                    {token(note)}
                </p>
            ) : null}
        </div>
    )
}

// ---------------------------------------------------------------------------
// property controls
// ---------------------------------------------------------------------------

const hideAuto = (p: any) => p.source === "auto"

addPropertyControls(FEPLeverageSpine, {
    source: {
        type: ControlType.Enum,
        title: "Source",
        options: ["manual", "auto"],
        optionTitles: ["Manual / CMS", "Auto (JSON)"],
        defaultValue: "manual",
        description:
            "Manual takes the three lists below, so you can bind them to CMS " +
            "text fields. Auto reads `leverage` out of the week file.",
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
    },
    baseUrl: {
        type: ControlType.String,
        title: "Data base URL",
        defaultValue: "",
        placeholder: "https://raw.githubusercontent.com/.../chart-data",
        hidden: (p: any) => p.source !== "auto",
    },

    labels: {
        type: ControlType.String,
        title: "Labels",
        defaultValue:
            "vs Commanders, @ Chiefs, vs Rams, @ Buccaneers, vs Broncos, @ Giants, vs Cowboys, @ Commanders, vs Packers, @ Cowboys, vs Bears, @ Chargers, vs Raiders, @ Bills, vs Lions, @ Jaguars, vs Giants",
        displayTextArea: true,
        description: "One game per entry, in schedule order.",
        hidden: hideAuto,
    },
    leverages: {
        type: ControlType.String,
        title: "Leverage",
        defaultValue:
            "9.1, 7.4, 11.2, 8.8, 10.4, 14.7, 19.3, 16.1, 12.6, 21.8, 13.9, 17.2, 11.5, 24.6, 22.1, 18.4, 26.3",
        displayTextArea: true,
        description: "Percentages, same order as Labels.",
        hidden: hideAuto,
    },
    results: {
        type: ControlType.String,
        title: "Results",
        defaultValue: "W, L, W, , , , , , , , , , , , , , ",
        displayTextArea: true,
        description:
            "W, L or T. Leave an entry blank for a game that has not been " +
            "played. The first blank is the next game unless you pin one.",
        hidden: hideAuto,
    },
    shortLabels: {
        type: ControlType.String,
        title: "Short labels",
        defaultValue:
            "WSH, TEN, CHI, LAR, JAX, CAR, DAL, WSH, NYG, PIT, DAL, ARI, IND, SEA, HOU, SF, NYG",
        displayTextArea: true,
        placeholder: "WSH, TEN, CHI, ...",
        description:
            "Used on narrow frames. Left empty, each one is derived from the " +
            "full label.",
        hidden: hideAuto,
    },
    separator: {
        type: ControlType.String,
        title: "Separator",
        defaultValue: ",",
        description: "What splits the lists above.",
        hidden: hideAuto,
    },
    nextGame: {
        type: ControlType.Number,
        title: "Next game",
        defaultValue: 0,
        min: 0,
        max: 18,
        step: 1,
        displayStepper: true,
        description:
            "Which game to highlight, counting from 1. Leave at 0 to use the " +
            "first one with no result.",
        hidden: hideAuto,
    },

    showEyebrow: { type: ControlType.Boolean, title: "Eyebrow", defaultValue: true },
    eyebrow: {
        type: ControlType.String,
        title: "Custom eyebrow",
        defaultValue: "",
        placeholder: "2026 | Week 7",
        hidden: (p: any) => !p.showEyebrow,
    },
    showTitle: { type: ControlType.Boolean, title: "Title", defaultValue: true },
    title: {
        type: ControlType.String,
        title: "Title text",
        defaultValue: "Leverage Index",
        hidden: (p: any) => !p.showTitle,
    },
    showSubtitle: { type: ControlType.Boolean, title: "Subtitle", defaultValue: true },
    subtitle: {
        type: ControlType.String,
        title: "Subtitle text",
        defaultValue:
            "Every game of the season, as tall as the share of the leaderboard riding on it.",
        displayTextArea: true,
        hidden: (p: any) => !p.showSubtitle,
    },
    showFoot: { type: ControlType.Boolean, title: "Footnote", defaultValue: true },
    foot: {
        type: ControlType.String,
        title: "Footnote text",
        defaultValue: "{topLabel} carries the most leverage left, at {topValue}.",
        displayTextArea: true,
        description:
            "Tokens: {topLabel} {topValue} {nextLabel} {nextValue} {played} " +
            "{remaining} {week} {year}. They work in the title and subtitle too.",
        hidden: (p: any) => !p.showFoot,
    },
    showNote: { type: ControlType.Boolean, title: "Mixed units note", defaultValue: false },
    note: {
        type: ControlType.String,
        title: "Note text",
        defaultValue:
            "Played games show what the result actually moved. Unplayed games show what it could.",
        displayTextArea: true,
        hidden: (p: any) => !p.showNote,
    },
    showKey: { type: ControlType.Boolean, title: "Key", defaultValue: true },
    keyRemaining: {
        type: ControlType.String,
        title: "Key: to play",
        defaultValue: "Still to play",
        hidden: (p: any) => !p.showKey,
    },
    keyNext: {
        type: ControlType.String,
        title: "Key: next",
        defaultValue: "Next up",
        hidden: (p: any) => !p.showKey,
    },
    keyWin: {
        type: ControlType.String,
        title: "Key: won",
        defaultValue: "Won",
        hidden: (p: any) => !p.showKey,
    },
    keyLoss: {
        type: ControlType.String,
        title: "Key: lost",
        defaultValue: "Lost",
        hidden: (p: any) => !p.showKey,
    },
    emptyText: {
        type: ControlType.String,
        title: "Empty state",
        defaultValue: "No leverage for this week yet.",
    },

    valueMode: {
        type: ControlType.Enum,
        title: "Numbers on bars",
        options: ["notable", "all", "none"],
        optionTitles: ["Next and biggest", "Every bar", "None"],
        defaultValue: "notable",
        description:
            "Every bar is a wall of digits that fights the shape. Two called " +
            "out on purpose carry the unit for the whole axis.",
    },
    valueSuffix: {
        type: ControlType.String,
        title: "Number suffix",
        defaultValue: "%",
        hidden: (p: any) => p.valueMode === "none",
    },
    valueDecimals: {
        type: ControlType.Number,
        title: "Decimals",
        defaultValue: 0,
        min: 0,
        max: 2,
        step: 1,
        displayStepper: true,
        hidden: (p: any) => p.valueMode === "none",
    },
    showAxisCaption: {
        type: ControlType.Boolean,
        title: "Axis caption",
        defaultValue: true,
        description:
            "Sits right above the bars. A percent sign says the unit; this " +
            "says percent of what.",
    },
    axisCaption: {
        type: ControlType.String,
        title: "Caption text",
        defaultValue:
            "Share of the whole leaderboard that swings on each result",
        displayTextArea: true,
        hidden: (p: any) => !p.showAxisCaption,
    },
    showStrip: { type: ControlType.Boolean, title: "Result strip", defaultValue: true },
    showNames: {
        type: ControlType.Boolean,
        title: "Game labels",
        defaultValue: true,
        description:
            "Full labels above 620px, short ones below, none under 380px.",
    },
    winMark: {
        type: ControlType.String,
        title: "Win mark",
        defaultValue: "W",
        hidden: (p: any) => !p.showStrip,
    },
    lossMark: {
        type: ControlType.String,
        title: "Loss mark",
        defaultValue: "L",
        hidden: (p: any) => !p.showStrip,
    },
    tieMark: {
        type: ControlType.String,
        title: "Tie mark",
        defaultValue: "T",
        hidden: (p: any) => !p.showStrip,
    },
    pendingMark: {
        type: ControlType.String,
        title: "Unplayed mark",
        defaultValue: "",
        placeholder: "leave blank, or try a dot",
        hidden: (p: any) => !p.showStrip,
    },

    fontFamily: { type: ControlType.String, title: "Font", defaultValue: "Maven Pro" },
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

    plotHeight: {
        type: ControlType.Number,
        title: "Plot height",
        defaultValue: 180,
        min: 60,
        max: 480,
        step: 5,
        unit: "px",
    },
    barGap: {
        type: ControlType.Number,
        title: "Bar gap",
        defaultValue: 4,
        min: 0,
        max: 20,
        step: 1,
        unit: "px",
    },
    barWidth: {
        type: ControlType.Number,
        title: "Bar width",
        defaultValue: 100,
        min: 10,
        max: 100,
        step: 5,
        unit: "%",
        description: "Of its slot. Below 100 the bars thin without moving.",
    },
    barRadius: {
        type: ControlType.Number,
        title: "Bar corner",
        defaultValue: 4,
        min: 0,
        max: 20,
        step: 1,
        unit: "px",
        description: "Top corners only. The bottom stays flat on the baseline.",
    },
    scaleMode: {
        type: ControlType.Enum,
        title: "Scale",
        options: ["auto", "fixed"],
        optionTitles: ["Tallest bar fills", "Fixed ceiling"],
        defaultValue: "auto",
        description:
            "Auto makes the shape readable every week. Fixed makes weeks " +
            "comparable to each other.",
    },
    scaleMax: {
        type: ControlType.Number,
        title: "Ceiling",
        defaultValue: 100,
        min: 5,
        max: 100,
        step: 5,
        unit: "%",
        hidden: (p: any) => p.scaleMode !== "fixed",
    },

    remainingColor: {
        type: ControlType.Color,
        title: "To play",
        defaultValue: "#4ED9B0",
    },
    nextColor: { type: ControlType.Color, title: "Next up", defaultValue: "#F2C14E" },
    winColor: { type: ControlType.Color, title: "Won", defaultValue: "#2C7A66" },
    lossColor: { type: ControlType.Color, title: "Lost", defaultValue: "#8C3B3B" },
    tieColor: { type: ControlType.Color, title: "Tied", defaultValue: "#5A6B68" },
    playedOpacity: {
        type: ControlType.Number,
        title: "Played fade",
        defaultValue: 0.85,
        min: 0.2,
        max: 1,
        step: 0.05,
        description: "The past sits back so the future reads forward.",
    },
    baselineColor: {
        type: ControlType.Color,
        title: "Baseline",
        defaultValue: "rgba(255,255,255,0.16)",
    },
    nextOutline: {
        type: ControlType.Boolean,
        title: "Ring next game",
        defaultValue: true,
    },

    reveal: {
        type: ControlType.Enum,
        title: "Reveal",
        options: ["inView", "onLoad", "off"],
        optionTitles: ["When scrolled into view", "On page load", "Off"],
        defaultValue: "inView",
        description: "Bars rise left to right, one game after another.",
    },
    revealAmount: {
        type: ControlType.Number,
        title: "Fires at",
        defaultValue: 0.35,
        min: 0,
        max: 1,
        step: 0.05,
        hidden: (p: any) => p.reveal !== "inView",
    },
    revealReplay: {
        type: ControlType.Boolean,
        title: "Replay",
        defaultValue: false,
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
        hidden: (p: any) => p.reveal === "off",
    },
    revealStagger: {
        type: ControlType.Number,
        title: "Stagger",
        defaultValue: 45,
        min: 0,
        max: 400,
        step: 5,
        unit: "ms",
        description: "Per game. 17 games at 45ms is a 0.77s sweep.",
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
})
