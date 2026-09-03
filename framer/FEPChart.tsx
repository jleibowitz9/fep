import { addPropertyControls, ControlType } from "framer"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

/**
 * FEP Championship Odds Chart
 * ==========================
 *
 * One component for every newsletter. Set `week` on each CMS entry and it
 * renders weeks 0 through that week, nothing after.
 *
 * This replaces the old setup of a hidden "Weighted - W7" sheet tab per week
 * plus a chart-component variant per week. Each week's data lives in its own
 * immutable JSON file, so an old newsletter can never start showing future
 * weeks, and the file can be cached forever.
 *
 * Data URL is `${baseUrl}/week-${week}.json`, written by the FEP simulator.
 *
 * What it fixes about the previous chart:
 *   - hovering shows ONE competitor, not all twelve including the dead ones
 *   - no legend: names sit at the end of their own lines on desktop, and
 *     become tappable chips on mobile
 *   - eliminated competitors stop riding the zero line; their line ends with a
 *     cross on the week they were eliminated
 *   - the y-axis fits the data instead of always drawing 0 to 100
 *   - a W/L strip under the axis ties every move to the game that caused it
 */

type Series = {
    name: string
    color: string
    values: (number | null)[]
    eliminatedAt: number | null
}

type Payload = {
    year: number
    week: number
    labels: string[]
    weeks: number[]
    series: Series[]
    games: { week: number; label: string | null; result: string | null }[]
    ranks: Record<string, number>[]
}

const DIM = "#4a5568"

type Props = {
    baseUrl?: string
    week?: number
    title?: string
    showTitle?: boolean
    showResults?: boolean
    background?: string
    ink?: string
    muted?: string
    grid?: string
    style?: React.CSSProperties
}

/**
 * Framer reads these annotations from the comment directly above the exported
 * component, so they have to live here rather than in the file header.
 *
 * @framerSupportedLayoutWidth any
 * @framerSupportedLayoutHeight any
 */
export default function FEPChart({
    baseUrl = "",
    week = 1,
    title = "",
    showTitle = true,
    showResults = true,
    background = "linear-gradient(160deg,#04302a,#06231f)",
    ink = "#eafaf6",
    muted = "#7f9c96",
    grid = "#12463f",
    style,
}: Props) {

    const [data, setData] = useState<Payload | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [pinned, setPinned] = useState<string | null>(null)
    const [hover, setHover] = useState<string | null>(null)
    const [tip, setTip] = useState<any>(null)
    const [width, setWidth] = useState(760)

    const hostNode = useRef<HTMLDivElement | null>(null)
    const observer = useRef<ResizeObserver | null>(null)
    const svgRef = useRef<SVGSVGElement>(null)

    // A callback ref, not useEffect. While data is loading this component
    // returns a placeholder, so an effect with [] deps would run once against a
    // null ref and never observe anything: width would stay at its default and
    // the chart would render desktop-width layout inside a phone-width box.
    const hostRef = useCallback((node: HTMLDivElement | null) => {
        if (observer.current) {
            observer.current.disconnect()
            observer.current = null
        }
        hostNode.current = node
        if (!node || typeof ResizeObserver === "undefined") return
        setWidth(node.getBoundingClientRect().width || 760)
        observer.current = new ResizeObserver((entries) =>
            setWidth(entries[0].contentRect.width)
        )
        observer.current.observe(node)
    }, [])

    // ---- data ------------------------------------------------------------
    const url = useMemo(() => {
        if (!baseUrl) return null
        const base = String(baseUrl).replace(/\/+$/, "")
        return `${base}/week-${String(week).padStart(2, "0")}.json`
    }, [baseUrl, week])

    useEffect(() => {
        if (!url) return
        let cancelled = false
        setError(null)
        fetch(url)
            .then((r) => {
                if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
                return r.json()
            })
            .then((json) => !cancelled && setData(json))
            .catch((e) => !cancelled && setError(String(e.message || e)))
        return () => {
            cancelled = true
        }
    }, [url])

    const narrow = width < 520

    // ---- geometry --------------------------------------------------------
    const W = 760
    const H = narrow ? 560 : 420

    const geo = useMemo(() => {
        if (!data) return null
        const left = narrow ? 30 : 36
        const right = 14  // no end labels, so the plot gets the width
        const top = 20
        const bottom = showResults ? 54 : 34

        let maxV = 0
        data.series.forEach((s) =>
            s.values.forEach((v) => {
                if (v && v > maxV) maxV = v
            })
        )
        // Round up to the next 5% and stop. No decorative headroom: a week
        // topping out at 36.6 draws to 40, not 50.
        const ceil = Math.max(5, Math.ceil(maxV / 5) * 5)
        // The largest round step that divides the ceiling EXACTLY and still
        // leaves at least three bands. Exact division matters: with a ceiling
        // of 35 and a step of 10 the top gridline lands on 30 and the axis
        // appears to stop short of its own maximum.
        let step = 5
        for (const c of [5, 10, 15, 20, 25, 50]) {
            if (ceil % c === 0 && ceil / c >= 3) step = c
        }
        const n = data.weeks.length

        return {
            left,
            right,
            top,
            bottom,
            ceil,
            step,
            x: (i: number) =>
                left + (W - left - right) * (n === 1 ? 0.5 : i / (n - 1)),
            y: (v: number) => top + (H - top - bottom) * (1 - v / ceil),
        }
    }, [data, narrow, H, showResults])

    // Trim trailing zeros so an eliminated line terminates instead of crawling.
    const drawn = useMemo(() => {
        if (!data) return []
        return data.series.map((s) => {
            let last = -1
            s.values.forEach((v, i) => {
                if (v !== null && v > 0) last = i
            })
            const upto = last < 0 ? 0 : Math.min(last + 1, s.values.length - 1)
            return { s, upto, out: s.eliminatedAt !== null && s.eliminatedAt !== undefined }
        })
    }, [data])

    if (!baseUrl)
        return <Notice style={style} ink={ink} text="Set the Data base URL in the properties panel." />
    if (error)
        return <Notice style={style} ink={ink} text={`Could not load week ${week}: ${error}`} />
    if (!data || !geo)
        return <Notice style={style} ink={muted} text="Loading..." />

    const focus = pinned || hover
    const n = data.weeks.length
    const lastIndex = n - 1

    // ---- interaction -----------------------------------------------------
    function locate(clientX: number, clientY: number) {
        const svg = svgRef.current
        if (!svg || !geo) return null
        const r = svg.getBoundingClientRect()
        const mx = ((clientX - r.left) / r.width) * W
        const my = ((clientY - r.top) / r.height) * H
        const step = (W - geo.left - geo.right) / Math.max(1, n - 1)
        let i = Math.round((mx - geo.left) / step)
        i = Math.max(0, Math.min(n - 1, i))

        let best: Series | null = null
        let bestD = Infinity
        data.series.forEach((s) => {
            const v = s.values[i]
            if (v === null || v === undefined) return
            // Do not offer a dead competitor on a week after their elimination.
            if (s.eliminatedAt !== null && s.eliminatedAt !== undefined && data.weeks[i] > s.eliminatedAt)
                return
            const d = Math.abs(geo.y(v) - my)
            if (d < bestD) {
                bestD = d
                best = s
            }
        })
        return best && bestD < 42 ? { s: best as Series, i } : null
    }

    function onMove(e: any) {
        const p = e.touches ? e.touches[0] : e
        const hit = locate(p.clientX, p.clientY)
        setHover(hit ? hit.s.name : null)
        if (!hit) return setTip(null)
        const { s, i } = hit
        const v = s.values[i]
        const prev = i > 0 ? s.values[i - 1] : null

        // Convert the hovered point into host-relative pixels using the real
        // element boxes. Deriving it from the viewBox alone silently ignores
        // the header above the SVG and lands the tooltip in the wrong place.
        const svgBox = svgRef.current?.getBoundingClientRect()
        const hostBox = hostNode.current?.getBoundingClientRect()
        let px = 0
        let py = 0
        if (svgBox && hostBox) {
            px = (geo.x(i) / W) * svgBox.width + (svgBox.left - hostBox.left)
            py = (geo.y(v as number) / H) * svgBox.height + (svgBox.top - hostBox.top)
        }

        setTip({
            name: s.name,
            color: s.color,
            label: data.labels[i],
            game: data.games[i],
            value: v,
            rank: data.ranks[i][s.name],
            total: data.series.length,
            delta: prev === null || prev === undefined || v === null ? null : v - prev,
            px,
            py,
        })
    }
    function onLeave() {
        setHover(null)
        setTip(null)
    }

    const every = narrow ? (n > 10 ? 3 : 2) : 1

    return (
        <div
            ref={hostRef}
            style={{
                ...style,
                background,
                color: ink,
                borderRadius: 14,
                padding: "18px 16px 14px",
                position: "relative",
                fontFamily:
                    'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
                boxSizing: "border-box",
            }}
        >
            {showTitle && (
                <div style={{ marginBottom: 20 }}>
                    <div
                        style={{
                            fontSize: narrow ? 16 : 19,
                            fontWeight: 800,
                            fontStyle: "italic",
                            letterSpacing: 0.2,
                        }}
                    >
                        {title || `${data.year} Family Eagles Pool | ${data.labels[lastIndex]}`}
                    </div>
                </div>
            )}

            <svg
                ref={svgRef}
                viewBox={`0 0 ${W} ${H}`}
                style={{ display: "block", width: "100%", height: "auto", touchAction: "pan-y" }}
                onMouseMove={onMove}
                onMouseLeave={onLeave}
                onTouchStart={onMove}
                onTouchMove={onMove}
                onTouchEnd={onLeave}
                role="img"
                aria-label={`Championship odds through ${data.labels[lastIndex]}`}
            >
                {/* vertical gridlines, one per week, set well behind the
                    horizontal value lines so they guide without competing */}
                {data.labels.map((_, i) => (
                    <line
                        key={`v${i}`}
                        x1={geo.x(i)}
                        x2={geo.x(i)}
                        y1={geo.top}
                        y2={H - geo.bottom}
                        stroke={grid}
                        strokeWidth={1}
                        opacity={0.42}
                    />
                ))}

                {/* horizontal gridlines and y axis */}
                {Array.from({ length: Math.floor(geo.ceil / geo.step) + 1 }, (_, g) => {
                    const v = g * geo.step
                    const y = geo.y(v)
                    return (
                        <g key={`g${g}`}>
                            <line x1={geo.left} x2={W - geo.right + 6} y1={y} y2={y} stroke={grid} strokeWidth={1} />
                            <text
                                x={geo.left - 7}
                                y={y + 3.5}
                                fill={muted}
                                fontSize={10.5}
                                textAnchor="end"
                                style={{ fontVariantNumeric: "tabular-nums" }}
                            >
                                {Math.round(v)}%
                            </text>
                        </g>
                    )
                })}

                {/* x axis */}
                {data.labels.map((lab, i) =>
                    i % every === 0 || i === lastIndex ? (
                        <text
                            key={`x${i}`}
                            x={geo.x(i)}
                            y={H - geo.bottom + 16}
                            fill={muted}
                            fontSize={10.5}
                            textAnchor="middle"
                        >
                            {lab}
                        </text>
                    ) : null
                )}

                {/* what actually happened */}
                {showResults &&
                    data.games.map((gm, i) => {
                        if (i % every !== 0 && i !== lastIndex) return null
                        const bye = !gm.result
                        const win = gm.result === "W"
                        const x = geo.x(i)
                        const y = H - geo.bottom + 24
                        return (
                            <g key={`r${i}`}>
                                <rect
                                    x={x - 9}
                                    y={y}
                                    width={18}
                                    height={14}
                                    rx={4}
                                    fill={bye ? "#2c4a45" : win ? "#1f7a4d" : "#7a2130"}
                                />
                                <text
                                    x={x}
                                    y={y + 10.2}
                                    fill={ink}
                                    fontSize={9.5}
                                    fontWeight={800}
                                    textAnchor="middle"
                                >
                                    {bye ? "–" : gm.result}
                                </text>
                            </g>
                        )
                    })}

                {/* lines, leaders painted last so they sit on top */}
                {drawn
                    .slice()
                    .sort((a, b) => (a.s.values[lastIndex] || 0) - (b.s.values[lastIndex] || 0))
                    .map(({ s, upto, out }) => {
                        const pts: [number, number][] = []
                        for (let i = 0; i <= upto; i++) {
                            const v = s.values[i]
                            if (v === null || v === undefined) continue
                            pts.push([geo.x(i), geo.y(v)])
                        }
                        if (!pts.length) return null
                        const dimmed = !!focus && focus !== s.name
                        const color = out ? DIM : s.color
                        const last = pts[pts.length - 1]
                        const k = 4.2
                        const quiet = out && focus !== s.name
                        return (
                            <g key={s.name} opacity={dimmed ? 0.12 : quiet ? 0.45 : 1}>
                                <path
                                    d={"M" + pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("L")}
                                    fill="none"
                                    stroke={color}
                                    strokeWidth={out ? 2.1 : 3}
                                    strokeLinejoin="round"
                                    strokeLinecap="round"
                                />
                                {/* A dot at every vertex, so each week is a real
                                    data point. Live competitors only: dotting the
                                    dead lines was most of the visual noise. */}
                                {(!out || focus === s.name) &&
                                    pts.slice(0, -1).map((p, pi) => (
                                        <circle
                                            key={`p${pi}`}
                                            cx={p[0]}
                                            cy={p[1]}
                                            r={3.3}
                                            fill={color}
                                        />
                                    ))}
                                {out ? (
                                    <>
                                        <path
                                            d={`M${last[0] - k},${last[1] - k}L${last[0] + k},${last[1] + k}`}
                                            stroke={color}
                                            strokeWidth={2.2}
                                            strokeLinecap="round"
                                        />
                                        <path
                                            d={`M${last[0] + k},${last[1] - k}L${last[0] - k},${last[1] + k}`}
                                            stroke={color}
                                            strokeWidth={2.2}
                                            strokeLinecap="round"
                                        />
                                    </>
                                ) : (
                                    <circle cx={last[0]} cy={last[1]} r={4.2} fill={color} />
                                )}
                            </g>
                        )
                    })}

            </svg>

            {tip && (
                <div
                    style={{
                        position: "absolute",
                        pointerEvents: "none",
                        // Flip to the left of the point when close to the right
                        // edge, so the tooltip never runs off a phone screen.
                        left:
                            tip.px + 14 + 170 > width
                                ? Math.max(4, tip.px - 184)
                                : tip.px + 14,
                        top: Math.max(4, tip.py - 12),
                        background: "#041e1af5",
                        border: "1px solid #ffffff30",
                        borderRadius: 10,
                        padding: "9px 11px",
                        fontSize: 12,
                        minWidth: 150,
                        boxShadow: "0 8px 24px #00000073",
                        zIndex: 5,
                    }}
                >
                    <b style={{ color: tip.color, fontSize: 13.5, fontWeight: 800 }}>{tip.name}</b>
                    <div style={{ marginTop: 4, fontSize: 11.5, color: "#cfe3df", fontWeight: 600 }}>
                        {tip.label}
                        {tip.game && tip.game.label
                            ? `  ${tip.game.label}${tip.game.result ? `  (${tip.game.result})` : ""}`
                            : "  bye week"}
                    </div>
                    <Row label="Odds" value={tip.value === null ? "--" : `${tip.value.toFixed(1)}%`} muted={muted} />
                    <Row label="Rank" value={`${tip.rank} of ${tip.total}`} muted={muted} />
                    {tip.delta !== null && (
                        <Row
                            label="Change"
                            value={`${tip.delta > 0 ? "+" : ""}${tip.delta.toFixed(1)}`}
                            muted={muted}
                            color={tip.delta > 0 ? "#3ddc97" : tip.delta < 0 ? "#ff7a7a" : undefined}
                        />
                    )}
                </div>
            )}

            {/* roster: the mobile legend, and tap to isolate anywhere.
                Ordered by current standing, then alphabetically, so it reads as
                the leaderboard rather than as an arbitrary roster. */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 11 }}>
                {data.series
                    .slice()
                    .sort((a, b) => {
                        const d = (b.values[lastIndex] || 0) - (a.values[lastIndex] || 0)
                        return d !== 0 ? d : a.name.localeCompare(b.name)
                    })
                    .map((s) => {
                    const out = s.eliminatedAt !== null && s.eliminatedAt !== undefined
                    const on = pinned === s.name
                    return (
                        <button
                            key={s.name}
                            type="button"
                            onClick={() => setPinned(on ? null : s.name)}
                            style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 5,
                                fontSize: 11,
                                fontWeight: 600,
                                padding: "4px 9px",
                                borderRadius: 999,
                                background: on ? "rgba(255,255,255,.12)" : "rgba(255,255,255,.05)",
                                border: `1px solid ${on ? s.color : "transparent"}`,
                                color: out ? muted : s.color,
                                textDecoration: out ? "line-through" : "none",
                                opacity: out ? 0.65 : 1,
                                cursor: "pointer",
                                fontFamily: "inherit",
                            }}
                        >
                            <span
                                style={{
                                    width: 8,
                                    height: 8,
                                    borderRadius: 2,
                                    background: out ? DIM : s.color,
                                    flex: "none",
                                }}
                            />
                            {s.name}
                            {!out && (
                                <span style={{ opacity: 0.75, fontVariantNumeric: "tabular-nums" }}>
                                    {(s.values[lastIndex] || 0).toFixed(1)}%
                                </span>
                            )}
                        </button>
                    )
                })}
            </div>

        </div>
    )
}

function Row({ label, value, muted, color }: any) {
    return (
        <div style={{ display: "flex", justifyContent: "space-between", gap: 14, marginTop: 4 }}>
            <span style={{ color: muted, fontSize: 11.5 }}>{label}</span>
            <span
                style={{
                    color: color || "#ffffff",
                    fontWeight: 700,
                    fontSize: 11.5,
                    fontVariantNumeric: "tabular-nums",
                }}
            >
                {value}
            </span>
        </div>
    )
}

function Notice({ style, ink, text }: any) {
    return (
        <div
            style={{
                ...style,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                minHeight: 120,
                color: ink,
                fontSize: 13,
                fontFamily: "ui-sans-serif, system-ui, sans-serif",
                opacity: 0.8,
                padding: 16,
                textAlign: "center",
                boxSizing: "border-box",
            }}
        >
            {text}
        </div>
    )
}

addPropertyControls(FEPChart, {
    week: {
        type: ControlType.Number,
        title: "Week",
        defaultValue: 1,
        min: 0,
        max: 18,
        step: 1,
        displayStepper: true,
        description: "Bind this to the newsletter's week. 0 is the preseason board.",
    },
    baseUrl: {
        type: ControlType.String,
        title: "Data base URL",
        defaultValue: "",
        placeholder: "https://raw.githubusercontent.com/.../chart-data/2026",
        description: "Set once. The chart loads {baseUrl}/week-NN.json",
    },
    showTitle: { type: ControlType.Boolean, title: "Title", defaultValue: true },
    title: {
        type: ControlType.String,
        title: "Custom title",
        placeholder: "2026 Family Eagles Pool | W7",
        hidden: (p) => !p.showTitle,
    },
    showResults: {
        type: ControlType.Boolean,
        title: "W/L strip",
        defaultValue: true,
        description: "Show each week's actual game result under the axis.",
    },
    background: {
        type: ControlType.String,
        title: "Background",
        defaultValue: "linear-gradient(160deg,#04302a,#06231f)",
    },
    ink: { type: ControlType.Color, title: "Text", defaultValue: "#eafaf6" },
    muted: { type: ControlType.Color, title: "Muted", defaultValue: "#7f9c96" },
    grid: { type: ControlType.Color, title: "Grid", defaultValue: "#12463f" },
})
