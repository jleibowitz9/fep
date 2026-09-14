import { addPropertyControls, ControlType, RenderTarget } from "framer"
import { useEffect, useRef, useState } from "react"

/**
 * FEP Under the Hood
 * ==================
 *
 * The nerd drawer. Collapsed by default, which is a feature rather than a
 * compromise: the newsletter's job is the story, and this is the appendix that
 * three people will open and love.
 *
 * Generic on purpose
 * ------------------
 * A tile is a label, a big value, and one plain-English line underneath. It is
 * not "the ESPN tile" in code, because the interesting stat changes: this week
 * it is ESPN's season, in December it might be tiebreaker exposure or the
 * elimination clock. Six slots, three on by default, every string editable,
 * so a new stat is a CMS binding rather than a new component.
 *
 * The gloss line is what makes it work at both reading levels. Amir reads the
 * numeral, Buhduh reads the sentence, and neither one is bored or lost. A tile
 * with no gloss is a tile that only half the family can use.
 *
 * Accent
 * ------
 * Each tile carries a verdict: neutral, good or bad. That is how "ESPN is doing
 * worse than a coin flip" looks like a running joke instead of reading like a
 * table cell. Bind it to a text field and the sheet decides the colour.
 *
 * The open and close animates with a grid-template-rows transition rather than
 * max-height, so it moves to the drawer's real height with nothing to tune and
 * no clipping when the copy runs long.
 *
 * Collapsible is off by default. When it is off there is no button, no
 * chevron, and no open state, so the tiles would have had no entrance at all
 * while sitting on a page beside two components that animate. They fade in on
 * scroll instead, driven by the same speed and stagger controls.
 *
 * House rule: no em dashes and no en dashes in any string this renders.
 */

const FONT_URL =
    "https://fonts.googleapis.com/css2?family=Maven+Pro:wght@400;500;600;700;800&display=swap"

const SLOTS = [1, 2, 3, 4, 5, 6]

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

const EASINGS: Record<string, string> = {
    easeOut: "cubic-bezier(0.22, 1, 0.36, 1)",
    easeInOut: "cubic-bezier(0.65, 0, 0.35, 1)",
    overshoot: "cubic-bezier(0.34, 1.56, 0.64, 1)",
    linear: "linear",
}

/** Only used when the drawer is not collapsible. Otherwise opening is the cue. */
function useReveal(
    enabled: boolean,
    mode: string,
    amount: number,
    replay: boolean,
    still: boolean
): [any, boolean] {
    const ref = useRef<HTMLDivElement | null>(null)
    const off = !enabled || mode === "off" || still
    const [shown, setShown] = useState(off || mode === "onLoad")

    useEffect(() => {
        if (off) {
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
    }, [off, mode, amount, replay])

    return [ref, shown]
}

const CSS = `
.feputh{container-type:inline-size;box-sizing:border-box}
.feputh *{box-sizing:border-box}
.feputh-head{display:flex;align-items:center;gap:12px;width:100%;
  background:none;border:0;padding:0;margin:0;font:inherit;color:inherit;
  text-align:left}
.feputh-head[role="button"]:focus-visible{outline:2px solid currentColor;
  outline-offset:4px;border-radius:6px}
.feputh-heading{flex:1 1 auto;min-width:0}
.feputh-title{font-size:1.12em;font-weight:800;letter-spacing:-.01em;margin:0}
.feputh-hint{font-size:.82em;margin:3px 0 0}
.feputh-chev{flex:none;width:22px;height:22px;display:flex;align-items:center;
  justify-content:center;font-size:.8em;font-weight:800;line-height:1}
.feputh-chev svg{display:block}
/* 0fr to 1fr animates to the real height, so nothing is clipped and there is
   no magic max-height to keep in step with the copy. */
.feputh-body{display:grid;grid-template-rows:0fr}
.feputh-clip{overflow:hidden;min-height:0}
.feputh-tiles{display:grid;gap:10px}
.feputh-tile{border-radius:10px;padding:13px 14px;min-width:0}
.feputh-label{font-size:.7em;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;margin:0 0 7px}
.feputh-value{font-size:1.75em;font-weight:800;line-height:1.05;margin:0;
  font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.feputh-gloss{font-size:.84em;line-height:1.45;margin:7px 0 0}
.feputh-foot{font-size:.8em;line-height:1.5;margin:12px 0 0}
.feputh-empty{font-size:.88em;padding:14px 0 2px}

@container (min-width: 560px){
  .feputh-tiles{grid-template-columns:repeat(3,minmax(0,1fr))}
}
@container (max-width: 559px){
  .feputh-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}
  .feputh-value{font-size:1.45em}
}
@container (max-width: 380px){
  .feputh-tiles{grid-template-columns:minmax(0,1fr)}
}
@media (prefers-reduced-motion: reduce){
  .feputh-body,.feputh-tile,.feputh-chev{transition:none !important}
}
`

type Props = {
    collapsible?: boolean
    showTitle?: boolean
    title?: string
    showHint?: boolean
    hint?: string
    openHint?: string
    startOpen?: boolean
    showChevron?: boolean
    chevronClosed?: string
    chevronOpen?: string
    emptyText?: string
    showFoot?: boolean
    foot?: string
    columns?: "auto" | "one" | "two" | "three"
    fontFamily?: string
    fontSize?: number
    background?: string
    ink?: string
    muted?: string
    radius?: number
    padding?: number
    tileBackground?: string
    tileRadius?: number
    labelColor?: string
    glossColor?: string
    goodColor?: string
    badColor?: string
    neutralColor?: string
    accentStripe?: boolean
    tileGap?: number
    duration?: number
    easing?: string
    tileStagger?: number
    reveal?: "inView" | "onLoad" | "off"
    revealAmount?: number
    revealReplay?: boolean
    style?: React.CSSProperties
} & Record<string, any>

/**
 * Framer reads these annotations from the comment directly above the exported
 * component, so they have to live here rather than in the file header.
 *
 * @framerSupportedLayoutWidth any
 * @framerSupportedLayoutHeight auto
 * @framerIntrinsicWidth 640
 * @framerIntrinsicHeight 120
 */
export default function FEPUnderTheHood(props: Props) {
    const {
        collapsible = false,
        showTitle = true,
        title = "Under the Hood",
        showHint = true,
        hint = "For the three of you who want the machinery",
        openHint = "",
        startOpen = false,
        showChevron = true,
        chevronClosed = "",
        chevronOpen = "",
        emptyText = "Nothing in the drawer this week.",
        showFoot = false,
        foot = "",
        columns = "auto",
        fontFamily = "Maven Pro",
        fontSize = 14,
        background = "transparent",
        ink = "#eafaf6",
        muted = "#7f9c96",
        radius = 14,
        padding = 0,
        tileBackground = "rgba(255,255,255,0.045)",
        tileRadius = 10,
        labelColor = "#7f9c96",
        glossColor = "#7f9c96",
        goodColor = "#4ED9B0",
        badColor = "#E4785F",
        neutralColor = "#eafaf6",
        accentStripe = true,
        tileGap = 10,
        duration = 420,
        easing = "easeOut",
        tileStagger = 60,
        reveal = "inView",
        revealAmount = 0.35,
        revealReplay = false,
        style,
    } = props

    useWebFont(FONT_URL)

    const isCanvas =
        typeof RenderTarget !== "undefined" &&
        RenderTarget.current() === RenderTarget.canvas
    const reduced =
        typeof window !== "undefined" &&
        typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches
    const still = isCanvas || reduced

    // The canvas always shows the drawer open, otherwise it is unstylable.
    const [userOpen, setOpen] = useState(!!startOpen || isCanvas)
    useEffect(() => {
        setOpen(!!startOpen || isCanvas)
    }, [startOpen, isCanvas])
    // Not collapsible means permanently open, with nothing to press.
    const open = collapsible ? userOpen : true

    const [rootRef, revealed] = useReveal(
        !collapsible,
        reveal,
        num(revealAmount, 0.35),
        !!revealReplay,
        still
    )
    // Opening is the cue when there is a button. Scrolling is, when there is not.
    const tilesIn = collapsible ? open : revealed

    const ease = EASINGS[easing] || EASINGS.easeOut
    const dur = Math.max(0, num(duration, 420))
    const step = Math.max(0, num(tileStagger, 60))

    const tiles = SLOTS.map((slot) => ({
        slot,
        on: props["show" + slot] !== false,
        label: String(props["label" + slot] || ""),
        value: String(props["value" + slot] || ""),
        gloss: String(props["gloss" + slot] || ""),
        accent: String(props["accent" + slot] || "neutral").toLowerCase(),
    }))
        // A value is what a tile is for. A label with nothing under it is a
        // hole, and the sheet leaves one whenever a stat has not started yet:
        // ESPN has no place before a game is scored, and nobody is the most
        // volatile in the preseason.
        .filter((t) => t.on && t.value.trim())

    const accentFor = (accent: string): string =>
        accent === "good" ? goodColor : accent === "bad" ? badColor : neutralColor

    const shellStyle: any = {
        ...style,
        fontFamily: `"${fontFamily}", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`,
        fontSize: num(fontSize, 14),
        background,
        color: ink,
        borderRadius: num(radius, 14),
        padding: num(padding, 0),
    }

    const gridStyle: any = { gap: num(tileGap, 10) }
    if (columns === "one") gridStyle.gridTemplateColumns = "minmax(0,1fr)"
    if (columns === "two")
        gridStyle.gridTemplateColumns = "repeat(2,minmax(0,1fr))"
    if (columns === "three")
        gridStyle.gridTemplateColumns = "repeat(3,minmax(0,1fr))"

    const titleText = showTitle ? (title || "").trim() : ""
    const hintText = showHint
        ? ((open && openHint.trim() ? openHint : hint) || "").trim()
        : ""
    const chevron = collapsible && showChevron
    const hasHeader = !!titleText || !!hintText || chevron

    return (
        <div ref={rootRef} className="feputh" style={shellStyle}>
            <style>{CSS}</style>

            {hasHeader ? (
                <div
                    className="feputh-head"
                    // A non-collapsible header is a heading, not a control. It
                    // must not be a button: nothing happens when it is pressed,
                    // and a screen reader should not announce one.
                    role={collapsible ? "button" : undefined}
                    tabIndex={collapsible ? 0 : undefined}
                    aria-expanded={collapsible ? open : undefined}
                    style={{ cursor: collapsible ? "pointer" : "default" }}
                    onClick={
                        collapsible ? () => setOpen((was) => !was) : undefined
                    }
                    onKeyDown={
                        collapsible
                            ? (e: any) => {
                                  if (e.key === "Enter" || e.key === " ") {
                                      e.preventDefault()
                                      setOpen((was) => !was)
                                  }
                              }
                            : undefined
                    }
                >
                    <span className="feputh-heading">
                        {titleText ? (
                            <span
                                className="feputh-title"
                                style={{ display: "block" }}
                            >
                                {titleText}
                            </span>
                        ) : null}
                        {hintText ? (
                            <span
                                className="feputh-hint"
                                style={{
                                    color: muted,
                                    display: "block",
                                    marginTop: titleText ? 3 : 0,
                                }}
                            >
                                {hintText}
                            </span>
                        ) : null}
                    </span>
                    {chevron ? (
                        <span
                            className="feputh-chev"
                            style={{
                                color: muted,
                                transform: open ? "rotate(180deg)" : "none",
                                transition: still
                                    ? undefined
                                    : `transform ${dur}ms ${ease}`,
                            }}
                            aria-hidden="true"
                        >
                            {open && chevronOpen.trim()
                                ? chevronOpen
                                : !open && chevronClosed.trim()
                                  ? chevronClosed
                                  : null}
                            {!chevronOpen.trim() && !chevronClosed.trim() ? (
                                <svg width="13" height="8" viewBox="0 0 13 8">
                                    <path
                                        d="M1 1l5.5 5.5L12 1"
                                        fill="none"
                                        stroke="currentColor"
                                        strokeWidth="2"
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                    />
                                </svg>
                            ) : null}
                        </span>
                    ) : null}
                </div>
            ) : null}

            <div
                className="feputh-body"
                style={{
                    gridTemplateRows: open ? "1fr" : "0fr",
                    transition:
                        still || !collapsible
                            ? undefined
                            : `grid-template-rows ${dur}ms ${ease}`,
                }}
            >
                <div className="feputh-clip">
                    <div style={{ paddingTop: hasHeader ? 14 : 0 }}>
                        {tiles.length ? (
                            <div className="feputh-tiles" style={gridStyle}>
                                {tiles.map((tile, i) => (
                                    <div
                                        key={tile.slot}
                                        className="feputh-tile"
                                        style={{
                                            background: tileBackground,
                                            borderRadius: num(tileRadius, 10),
                                            borderLeft: accentStripe
                                                ? `3px solid ${accentFor(tile.accent)}`
                                                : "none",
                                            opacity: tilesIn ? 1 : 0,
                                            transform: tilesIn
                                                ? "none"
                                                : "translateY(6px)",
                                            transition: still
                                                ? undefined
                                                : `opacity ${Math.round(dur * 0.8)}ms ease-out ${tilesIn ? i * step : 0}ms, transform ${Math.round(dur * 0.8)}ms ${ease} ${tilesIn ? i * step : 0}ms`,
                                        }}
                                    >
                                        {tile.label ? (
                                            <p
                                                className="feputh-label"
                                                style={{ color: labelColor }}
                                            >
                                                {tile.label}
                                            </p>
                                        ) : null}
                                        <p
                                            className="feputh-value"
                                            style={{
                                                color: accentFor(tile.accent),
                                            }}
                                        >
                                            {tile.value}
                                        </p>
                                        {tile.gloss ? (
                                            <p
                                                className="feputh-gloss"
                                                style={{ color: glossColor }}
                                            >
                                                {tile.gloss}
                                            </p>
                                        ) : null}
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p
                                className="feputh-empty"
                                style={{ color: muted, margin: 0 }}
                            >
                                {emptyText}
                            </p>
                        )}
                        {showFoot && foot ? (
                            <p className="feputh-foot" style={{ color: muted }}>
                                {foot}
                            </p>
                        ) : null}
                    </div>
                </div>
            </div>
        </div>
    )
}

// ---------------------------------------------------------------------------
// property controls
// ---------------------------------------------------------------------------

/**
 * Six identical tiles means thirty near-identical control blocks, so they are
 * built in a loop instead. Insertion order is what the panel shows, which is
 * why the chrome goes in first, then the tiles, then the styling.
 */
const TILE_DEFAULTS: Record<number, {
    on: boolean
    label: string
    value: string
    gloss: string
    accent: string
}> = {
    1: {
        on: true,
        label: "ESPN's season",
        value: "9th",
        gloss:
            "It locked 13 wins in August and has 4 of 9 right. It expected 5.2 wins by now; the Eagles have 7.",
        accent: "bad",
    },
    2: {
        on: true,
        label: "Points model",
        value: "409 ± 40",
        gloss:
            "Where tiebreaker 3 thinks the season lands, off 9 games of scoring so far.",
        accent: "neutral",
    },
    3: {
        on: true,
        label: "Most volatile",
        value: "Marsha",
        gloss: "79.0 points of total movement, and a peak of 34.1% in Week 8.",
        accent: "neutral",
    },
    4: { on: false, label: "", value: "", gloss: "", accent: "neutral" },
    5: { on: false, label: "", value: "", gloss: "", accent: "neutral" },
    6: { on: false, label: "", value: "", gloss: "", accent: "neutral" },
}

const tileControls: Record<string, any> = {}
for (const slot of SLOTS) {
    const d = TILE_DEFAULTS[slot]
    const off = (p: any) => p["show" + slot] === false
    tileControls["show" + slot] = {
        type: ControlType.Boolean,
        title: "Tile " + slot,
        defaultValue: d.on,
    }
    tileControls["label" + slot] = {
        type: ControlType.String,
        title: "  " + slot + " label",
        defaultValue: d.label,
        placeholder: "ESPN's season",
        hidden: off,
    }
    tileControls["value" + slot] = {
        type: ControlType.String,
        title: "  " + slot + " value",
        defaultValue: d.value,
        placeholder: "9th",
        description: slot === 1 ? "The big number. Bind it to the sheet." : undefined,
        hidden: off,
    }
    tileControls["gloss" + slot] = {
        type: ControlType.String,
        title: "  " + slot + " gloss",
        defaultValue: d.gloss,
        displayTextArea: true,
        description:
            slot === 1
                ? "The plain-English line. Without it, only half the family can read the tile."
                : undefined,
        hidden: off,
    }
    tileControls["accent" + slot] = {
        type: ControlType.Enum,
        title: "  " + slot + " accent",
        options: ["neutral", "good", "bad"],
        optionTitles: ["Neutral", "Good", "Bad"],
        defaultValue: d.accent,
        hidden: off,
    }
}

addPropertyControls(FEPUnderTheHood, {
    collapsible: {
        type: ControlType.Boolean,
        title: "Collapsible",
        defaultValue: false,
        description:
            "Off means always open, with no button and nothing to press. " +
            "Turn it on to get the drawer back.",
    },
    showTitle: {
        type: ControlType.Boolean,
        title: "Title",
        defaultValue: true,
    },
    title: {
        type: ControlType.String,
        title: "Title text",
        defaultValue: "Under the Hood",
        hidden: (p: any) => !p.showTitle,
    },
    showHint: {
        type: ControlType.Boolean,
        title: "Hint",
        defaultValue: true,
    },
    hint: {
        type: ControlType.String,
        title: "Hint text",
        defaultValue: "For the three of you who want the machinery",
        displayTextArea: true,
        hidden: (p: any) => !p.showHint,
    },
    openHint: {
        type: ControlType.String,
        title: "Hint when open",
        defaultValue: "",
        placeholder: "leave blank to keep the same line",
        hidden: (p: any) => !p.showHint || !p.collapsible,
    },
    startOpen: {
        type: ControlType.Boolean,
        title: "Start open",
        defaultValue: false,
        description:
            "The canvas always shows it open so you can style it.",
        hidden: (p: any) => !p.collapsible,
    },
    showChevron: {
        type: ControlType.Boolean,
        title: "Chevron",
        defaultValue: true,
        hidden: (p: any) => !p.collapsible,
    },
    chevronClosed: {
        type: ControlType.String,
        title: "Closed glyph",
        defaultValue: "",
        placeholder: "leave blank for the arrow",
        hidden: (p: any) => !p.collapsible || !p.showChevron,
    },
    chevronOpen: {
        type: ControlType.String,
        title: "Open glyph",
        defaultValue: "",
        placeholder: "leave blank for the arrow",
        hidden: (p: any) => !p.collapsible || !p.showChevron,
    },

    ...tileControls,

    columns: {
        type: ControlType.Enum,
        title: "Columns",
        options: ["auto", "one", "two", "three"],
        optionTitles: ["Auto", "One", "Two", "Three"],
        defaultValue: "auto",
        description: "Auto is three across, two under 560px, one under 380px.",
    },
    emptyText: {
        type: ControlType.String,
        title: "Empty state",
        defaultValue: "Nothing in the drawer this week.",
    },
    showFoot: {
        type: ControlType.Boolean,
        title: "Footnote",
        defaultValue: false,
    },
    foot: {
        type: ControlType.String,
        title: "Footnote text",
        defaultValue: "",
        displayTextArea: true,
        hidden: (p: any) => !p.showFoot,
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
        defaultValue: "transparent",
        description:
            "Transparent by default, so the drawer sits inside whatever card " +
            "it is dropped into.",
    },
    ink: { type: ControlType.Color, title: "Text", defaultValue: "#eafaf6" },
    muted: { type: ControlType.Color, title: "Muted", defaultValue: "#7f9c96" },
    labelColor: {
        type: ControlType.Color,
        title: "Tile label",
        defaultValue: "#7f9c96",
    },
    glossColor: {
        type: ControlType.Color,
        title: "Tile gloss",
        defaultValue: "#7f9c96",
    },
    tileBackground: {
        type: ControlType.String,
        title: "Tile fill",
        defaultValue: "rgba(255,255,255,0.045)",
    },
    neutralColor: {
        type: ControlType.Color,
        title: "Accent neutral",
        defaultValue: "#eafaf6",
    },
    goodColor: {
        type: ControlType.Color,
        title: "Accent good",
        defaultValue: "#4ED9B0",
    },
    badColor: {
        type: ControlType.Color,
        title: "Accent bad",
        defaultValue: "#E4785F",
        description:
            "A predictor doing worse than a coin flip is a running joke and " +
            "should look like one.",
    },
    accentStripe: {
        type: ControlType.Boolean,
        title: "Accent stripe",
        defaultValue: true,
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
        defaultValue: 0,
        min: 0,
        max: 64,
        step: 1,
        unit: "px",
    },
    tileRadius: {
        type: ControlType.Number,
        title: "Tile corner",
        defaultValue: 10,
        min: 0,
        max: 32,
        step: 1,
        unit: "px",
    },
    tileGap: {
        type: ControlType.Number,
        title: "Tile gap",
        defaultValue: 10,
        min: 0,
        max: 40,
        step: 1,
        unit: "px",
    },

    reveal: {
        type: ControlType.Enum,
        title: "Reveal",
        options: ["inView", "onLoad", "off"],
        optionTitles: ["When scrolled into view", "On page load", "Off"],
        defaultValue: "inView",
        description:
            "How the tiles arrive when there is no drawer to open. Ignored " +
            "while Collapsible is on, where opening is the cue.",
        hidden: (p: any) => p.collapsible,
    },
    revealAmount: {
        type: ControlType.Number,
        title: "Fires at",
        defaultValue: 0.35,
        min: 0,
        max: 1,
        step: 0.05,
        hidden: (p: any) => p.collapsible || p.reveal !== "inView",
    },
    revealReplay: {
        type: ControlType.Boolean,
        title: "Replay",
        defaultValue: false,
        hidden: (p: any) => p.collapsible || p.reveal !== "inView",
    },
    duration: {
        type: ControlType.Number,
        title: "Speed",
        defaultValue: 420,
        min: 0,
        max: 2000,
        step: 20,
        unit: "ms",
    },
    tileStagger: {
        type: ControlType.Number,
        title: "Tile stagger",
        defaultValue: 60,
        min: 0,
        max: 400,
        step: 10,
        unit: "ms",
        description: "Tiles arrive one after another as the drawer opens.",
    },
    easing: {
        type: ControlType.Enum,
        title: "Easing",
        options: ["easeOut", "easeInOut", "overshoot", "linear"],
        optionTitles: ["Ease out", "Ease in out", "Overshoot", "Linear"],
        defaultValue: "easeOut",
    },
})
