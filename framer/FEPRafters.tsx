// FEP Rafters: elimination banners hoisted into the arena rafters.
// Framer code component. Paste into a new code file in Framer (Assets > Code > New File).
//
// Two sources, and manual is the default:
//
//   Manual   the banners come from the Competitors array, filled by hand.
//   Auto     fetch {baseUrl}/{year}/week-NN.json and read its `rafters` block.
//            Banners, this week's names, the empty hooks and the season label
//            all come from the file.
//
// Photos in both modes come from the Profile Pictures component, one variant
// per competitor named by first name. A Manual competitor's own Photo, if
// set, wins over it.
//
// Framer cannot bind CMS rows into an array prop, which is why Auto reads the
// week file rather than the CMS. The newsletter still binds this component's
// visibility to `weeks.eliminated_this_week`, so it only shows in weeks with an
// elimination.

import * as React from "react"
import { useEffect, useMemo, useRef, useState, useId } from "react"
import { addPropertyControls, ControlType, RenderTarget } from "framer"
import { useInView } from "framer-motion"
import ProfilePictures from "https://framer.com/m/Profile-Pictures-D5IVuk.js@XYSR2b2CKDBIqnqlk9u1"

// ---------- Base geometry (everything scales to the component's height) ----------
const ARENA_H = 660 // the default arena; the real one follows the Spacing gaps below the banner
const TRUSS_TOP = 18
const TRUSS_H = 44
const PULLEY_TOP = 54
const CLIP_TOP = 74
const ROPE_VISIBLE = 34
const LIFT_W = 212
const BANNER_W = 196
const BANNER_H = 432
const ROPE_OFFSET = 76
const BANNER_BOTTOM = 546 // the tassel's tip, a hoisted banner's lowest point
const NEWTAG_H = 20
const RIBBON_H = 34
const DROP = 700

// Three hand-over-hand pulls, a small sag after each, a slight overshoot at the top.
const LIFT_STEPS: [number, number][] = [
    [0, 1], [0.24, 0.63], [0.31, 0.655], [0.55, 0.3], [0.62, 0.322], [0.86, -0.012], [0.93, 0.004], [1, 0],
]
const EASE = "cubic-bezier(.35,0,.22,1)"

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

type Competitor = {
    name: string
    photo?: { src?: string; srcSet?: string; alt?: string }
    week: number
    peak: string
    picks: string
    status: "past" | "new"
}

// The week file's `rafters` block, as written by fep/cms.py.
type Rafters = {
    roster: number
    alive: number
    this_week: string[]
    banners: { name: string; color?: string; week: number; peak: number; correct: number; decided: number }[]
}

const DATA_URL = "https://raw.githubusercontent.com/jleibowitz9/fep/main/chart-data"

// Gaps between the banner's elements, top to bottom, in banner pixels.
// Written again as the Spacing control's defaults; keep the two in step.
const SPACING = {
    top: 24, seasonToPhoto: 12, photoToName: 14, nameToNumber: 10, numberToLabel: 8, labelToRule: 12, ruleToStats: 12, betweenStats: 4,
    bannerToBadge: 14, badgeToTicker: 24, tickerToBottom: 22,
}

function useFetchedRafters(enabled: boolean, baseUrl: string, year: number, week: number) {
    const [state, setState] = useState<{ rafters: Rafters | null; fileWeek: number; error: string | null }>({
        rafters: null, fileWeek: week, error: null,
    })

    useEffect(() => {
        if (!enabled) {
            setState({ rafters: null, fileWeek: week, error: null })
            return
        }
        if (!baseUrl) {
            setState({ rafters: null, fileWeek: week, error: "Set the data base URL." })
            return
        }
        // A base URL that already ends in a year still works, same as the chart.
        const base = String(baseUrl).replace(/\/+$/, "").replace(/\/\d{4}$/, "")
        const file = `week-${String(week).padStart(2, "0")}.json`
        const url = `${base}/${year}/${file}`

        let cancelled = false
        setState({ rafters: null, fileWeek: week, error: null })
        fetch(url)
            .then((r) => {
                if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
                return r.json()
            })
            .then((payload: any) => {
                if (cancelled) return
                const rafters = payload && payload.rafters
                if (!rafters || !Array.isArray(rafters.banners)) {
                    setState({ rafters: null, fileWeek: week, error: `${year} ${file} has no rafters block.` })
                    return
                }
                setState({ rafters, fileWeek: Number(payload.week ?? week), error: null })
            })
            .catch((e) => !cancelled && setState({ rafters: null, fileWeek: week, error: `Could not load ${year} ${file} (${e.message || e})` }))
        return () => {
            cancelled = true
        }
    }, [enabled, baseUrl, year, week])

    return state
}

const nameKey = (n: string) => String(n || "").trim().toLowerCase()

// The Profile Pictures variant for a competitor, or null for the silhouette.
// The variant names are read off the component itself, so a new competitor
// needs only a new variant there. Without this check an unknown name would
// fall back to the Primary variant and show Amir on someone else's banner.
// ERROR is that component's own placeholder, so it is never matched by name.
function photoVariant(name: string): string | null {
    const titles: unknown = (ProfilePictures as any)?.propertyControls?.variant?.optionTitles
    if (!Array.isArray(titles)) return name || null
    const hit = titles.find((t) => typeof t === "string" && t !== "ERROR" && nameKey(t) === nameKey(name))
    return hit || null
}

/**
 * @framerSupportedLayoutWidth any
 * @framerSupportedLayoutHeight fixed
 * @framerIntrinsicWidth 1000
 * @framerIntrinsicHeight 660
 */
export default function FEPRafters(rawProps: any) {
    // Every default is written twice, here and in addPropertyControls, because
    // Framer reads only the literal defaultValues there. Keep the two in step.
    const {
        source = "manual",
        year = 2026,
        week = 1,
        baseUrl = DATA_URL,
        competitors: manualCompetitors = [],
        emptyHooks: manualHooks = 5,
        showChampionHook: manualChampion = true,
        // content
        seasonLabel: seasonLabelProp = "", eliminatedLabel = "Week eliminated", peakLabel = "Peak",
        picksSuffix = "right", newTagText = "Eliminated this week", showNewTag = true,
        reservedLabel = "Reserved", championLabel = "Champion's hook. Always empty.",
        ribbonText = "Eliminated this week: {names}   ●   {season}   ●   {alive} still alive   ●   Go Birds   ●   ",
        showRibbon = true, showPhoto = true, grayscalePhotos = true,
        // colors
        bgTop = "#13252A", bgBottom = "#050B0C", bannerColor = "#33464A", bannerEdge = "#1C2729", trimColor = "#A9B3B5",
        stripeColor = "#566468", textColor = "#E4E9EA", numberTop = "#B9C2C4", numberBottom = "#7C898B",
        ropeColor = "#CDBF9C", trussColor = "#3A484B", ledColor = "#E3A857",
        spotColor = "rgba(255, 244, 214, 0.1)", tagColor = "#C4CCCE", tagTextColor = "#081113",
        // fonts
        nameFont = { fontSize: 34 }, numberFont = { fontSize: 94 }, labelFont = { fontSize: 11 },
        // motion
        trigger = 50, replayOnReenter = false, autoPan = true, hoistDuration = 3.6, gapBetween = 0.9,
        settleSwing = 2.4, idleSway = 0.45, dimAmount = 0.7, pastBrightness = 0.78, dust = 1, parallax = 0.42,
        reducedMotionSafe = true, arrivalShine = false,
        // layout
        slotWidth = 236, edgePadding = 180, cornerRadius = 8, showStripe = true, showTassel = true, edgeFade = 7,
        spacing = SPACING,
        style,
    } = rawProps

    // ---------- Source ----------
    const auto = source === "auto"
    const fetched = useFetchedRafters(auto, baseUrl, year, week)
    const rafters = auto ? fetched.rafters : null
    const ready = !auto || !!rafters

    const seasonLabel = seasonLabelProp || `FEP ${year}`
    const competitors: Competitor[] = useMemo(() => {
        if (!auto) return manualCompetitors || []
        if (!rafters) return []
        return rafters.banners.map((b) => ({
            name: b.name,
            week: b.week,
            peak: `${Number(b.peak).toFixed(1)}%`,
            picks: `${b.correct} of ${b.decided}`,
            status: (b.week === fetched.fileWeek ? "new" : "past") as Competitor["status"],
        }))
    }, [auto, manualCompetitors, rafters, fetched.fileWeek])
    const emptyHooks = auto ? (rafters ? rafters.alive - 1 : 0) : manualHooks
    const showChampionHook = auto ? !!rafters : manualChampion

    // Banner reads the resolved values, not the raw props.
    const props = { ...rawProps, seasonLabel, eliminatedLabel, peakLabel, picksSuffix, showPhoto, grayscalePhotos,
        bannerColor, bannerEdge, trimColor, stripeColor, textColor, numberTop, numberBottom,
        nameFont, numberFont, labelFont, pastBrightness, showStripe, showTassel, arrivalShine, spacing }

    const isCanvas = RenderTarget.current() === RenderTarget.canvas
    const rootRef = useRef<HTMLDivElement>(null)
    const scrollerRef = useRef<HTMLDivElement>(null)
    const farRef = useRef<HTMLDivElement>(null)
    const trussRef = useRef<HTMLDivElement>(null)
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const slotRefs = useRef<(HTMLDivElement | null)[]>([])
    const runRef = useRef(0)
    const uid = useId().replace(/:/g, "")

    // Below the banners: the badge, then the ticker, then the arena's floor.
    // The arena is as tall as that stack, and everything scales to fit it.
    const gap = { ...SPACING, ...(spacing || {}) }
    const tagTop = BANNER_BOTTOM + gap.bannerToBadge
    const ribbonTop = showNewTag ? tagTop + NEWTAG_H + gap.badgeToTicker : tagTop
    const arenaH = (showRibbon ? ribbonTop + RIBBON_H : showNewTag ? tagTop + NEWTAG_H : BANNER_BOTTOM) + gap.tickerToBottom

    // Scale to height
    const [h, setH] = useState(ARENA_H)
    const [w, setW] = useState(1000)
    useEffect(() => {
        const el = rootRef.current
        if (!el) return
        const ro = new ResizeObserver(() => {
            setH(el.clientHeight || ARENA_H)
            setW(el.clientWidth || 1000)
        })
        ro.observe(el)
        return () => ro.disconnect()
    }, [])
    const s = h / arenaH

    // Slots in order: competitors (as listed), then empty hooks, then champion hook
    const list: Competitor[] = competitors || []
    const newIdx = list.map((c, i) => (c.status === "new" ? i : -1)).filter((i) => i >= 0)
    const hooks = Math.max(0, Math.round(emptyHooks || 0))
    const totalSlots = list.length + hooks + (showChampionHook ? 1 : 0)
    // At least half the container either side, so any banner can be scrolled to
    // the middle. A lone banner at the start of the row could not otherwise be
    // centred, since the scroll stops at zero.
    const pad = Math.max(edgePadding, w / s / 2 - slotWidth / 2)
    const trackW = totalSlots * slotWidth + pad * 2
    const alive = hooks + (showChampionHook ? 1 : 0)
    const names = (rafters ? rafters.this_week : newIdx.map((i) => list[i].name)).join(" · ")
    const ribbon = (ribbonText || "").replace("{names}", names).replace("{alive}", String(alive)).replace("{season}", seasonLabel)

    // Ceremony state
    const reduce = reducedMotionSafe && typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    const skip = isCanvas || reduce
    const [phase, setPhase] = useState<"armed" | "running" | "done">(skip ? "done" : "armed")
    const [dark, setDark] = useState(false)
    const [lit, setLit] = useState<Set<number>>(new Set())
    const [arrived, setArrived] = useState<Set<number>>(new Set())
    const [arriveKey, setArriveKey] = useState<Record<number, number>>({})

    const inView = useInView(rootRef, { amount: Math.min(1, Math.max(0.01, trigger / 100)), once: !replayOnReenter })

    // ---------- Parallax ----------
    useEffect(() => {
        const sc = scrollerRef.current
        if (!sc) return
        const onScroll = () => {
            if (farRef.current) farRef.current.style.transform = `translateX(${(sc.scrollLeft / s) * parallax}px)`
        }
        onScroll()
        sc.addEventListener("scroll", onScroll, { passive: true })
        return () => sc.removeEventListener("scroll", onScroll)
    }, [s, parallax])

    const centerOn = (i: number, smooth = true) => {
        const sc = scrollerRef.current
        if (!sc) return
        const x = (pad + i * slotWidth + slotWidth / 2) * s - sc.clientWidth / 2
        sc.scrollTo({ left: Math.max(0, x), behavior: smooth ? "smooth" : "auto" })
    }

    // ---------- Dust ----------
    const parts = useRef<any[]>([])
    const raf = useRef(0)
    const dpr = typeof window !== "undefined" ? Math.min(2, (window.devicePixelRatio || 1) * Math.max(1, s)) : 1
    useEffect(() => {
        const cv = canvasRef.current
        if (!cv) return
        cv.width = trackW * dpr
        cv.height = arenaH * dpr
    }, [trackW, arenaH, dpr])
    const tick = () => {
        const cv = canvasRef.current
        if (!cv) return
        const ctx = cv.getContext("2d")!
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        ctx.clearRect(0, 0, trackW, arenaH)
        parts.current = parts.current.filter((p) => p.life < p.max)
        for (const p of parts.current) {
            p.life++
            p.vy += 0.018
            p.vx *= 0.985
            p.x += p.vx + Math.sin((p.life + p.r * 40) / 14) * 0.15
            p.y += p.vy
            const a = Math.min(1, p.life / 8) * (1 - p.life / p.max)
            ctx.fillStyle = `rgba(230,218,188,${a * 0.8})`
            ctx.beginPath()
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
            ctx.fill()
        }
        raf.current = parts.current.length ? requestAnimationFrame(tick) : 0
    }
    const burst = (x: number, y: number) => {
        for (let k = 0; k < Math.round(22 * dust); k++)
            parts.current.push({
                x: x + (Math.random() - 0.5) * 14, y: y + Math.random() * 4,
                vx: (Math.random() - 0.5) * 0.9, vy: Math.random() * 0.8 + 0.1,
                life: 0, max: 70 + Math.random() * 90, r: 0.6 + Math.random() * 1.7,
            })
        if (!raf.current) raf.current = requestAnimationFrame(tick)
    }
    useEffect(() => () => cancelAnimationFrame(raf.current), [])

    // ---------- Hoist + arrival ----------
    const hoist = (i: number) => {
        const slot = slotRefs.current[i]
        if (!slot) return Promise.resolve()
        const lift = slot.querySelector(".fr-lift") as HTMLElement
        const swing = slot.querySelector(".fr-swing") as HTMLElement
        const dur = hoistDuration * 1000
        const a = lift.animate(
            LIFT_STEPS.map(([o, f]) => ({ offset: o, transform: `translateY(${f * DROP}px)`, easing: EASE })),
            { duration: dur, fill: "forwards" }
        )
        slot.querySelectorAll(".fr-wheel").forEach((w, j) =>
            (w as HTMLElement).animate(
                LIFT_STEPS.map(([o, f]) => ({ offset: o, transform: `rotate(${(j ? -1 : 1) * (1 - f) * 1500}deg)`, easing: EASE })),
                { duration: dur, fill: "forwards" }
            )
        )
        const r = settleSwing * 0.38
        swing.animate(
            [
                { offset: 0, transform: "rotate(0deg)" }, { offset: 0.24, transform: `rotate(${r}deg)` },
                { offset: 0.33, transform: `rotate(${-r * 0.66}deg)` }, { offset: 0.55, transform: `rotate(${-r * 0.9}deg)` },
                { offset: 0.64, transform: `rotate(${r * 0.55}deg)` }, { offset: 0.86, transform: "rotate(0deg)" },
                { offset: 1, transform: "rotate(0deg)" },
            ],
            { duration: dur, easing: "ease-in-out" }
        )
        return a.finished.then(() => undefined).catch(() => undefined)
    }
    const arrive = (i: number) => {
        const slot = slotRefs.current[i]
        if (!slot) return
        const swing = slot.querySelector(".fr-swing") as HTMLElement
        const d = settleSwing
        swing.animate(
            [
                { transform: "rotate(0deg)" }, { transform: `rotate(${-d}deg)`, offset: 0.16 },
                { transform: `rotate(${d * 0.7}deg)`, offset: 0.36 }, { transform: `rotate(${-d * 0.42}deg)`, offset: 0.55 },
                { transform: `rotate(${d * 0.2}deg)`, offset: 0.72 }, { transform: `rotate(${-d * 0.08}deg)`, offset: 0.86 },
                { transform: "rotate(0deg)" },
            ],
            { duration: 2800, easing: "ease-in-out" }
        )
        setArriveKey((k) => ({ ...k, [i]: (k[i] || 0) + 1 }))
        trussRef.current?.animate(
            [{ transform: "translateY(0)" }, { transform: "translateY(1.5px)" }, { transform: "translateY(-.8px)" }, { transform: "translateY(0)" }],
            { duration: 260 }
        )
        if (dust > 0) {
            const cx = pad + i * slotWidth + slotWidth / 2
            burst(cx - ROPE_OFFSET, CLIP_TOP - 2)
            burst(cx + ROPE_OFFSET, CLIP_TOP - 2)
        }
    }

    const reset = () => {
        runRef.current++
        slotRefs.current.forEach((sl) => sl?.querySelectorAll(".fr-lift, .fr-wheel, .fr-swing").forEach((el) => (el as HTMLElement).getAnimations().forEach((a) => a.cancel())))
        setDark(false)
        setLit(new Set())
        setArrived(new Set())
        setPhase("armed")
    }

    const ceremony = async () => {
        const me = ++runRef.current
        setPhase("running")
        setArrived(new Set())
        setLit(new Set())
        if (!newIdx.length) { setPhase("done"); return }
        if (autoPan) scrollerRef.current?.scrollTo({ left: 0, behavior: "auto" })
        await sleep(400); if (me !== runRef.current) return
        setDark(true)
        await sleep(500); if (me !== runRef.current) return
        for (let n = 0; n < newIdx.length; n++) {
            const i = newIdx[n]
            if (autoPan) centerOn(i)
            await sleep(n ? 650 : 1000); if (me !== runRef.current) return
            setLit((p) => new Set(p).add(i))
            await sleep(500); if (me !== runRef.current) return
            await hoist(i); if (me !== runRef.current) return
            setArrived((p) => new Set(p).add(i))
            requestAnimationFrame(() => {
                const lift = slotRefs.current[i]?.querySelector(".fr-lift") as HTMLElement
                lift?.getAnimations().forEach((a) => a.cancel())
            })
            arrive(i)
            await sleep(gapBetween * 1000); if (me !== runRef.current) return
        }
        await sleep(500); if (me !== runRef.current) return
        setDark(false)
        setLit(new Set())
        setPhase("done")
        if (autoPan && newIdx.length) {
            const sc = scrollerRef.current
            if (sc) {
                const mid = (newIdx[0] + newIdx[newIdx.length - 1]) / 2
                const x = (pad + mid * slotWidth + slotWidth / 2) * s - sc.clientWidth / 2
                sc.scrollTo({ left: Math.max(0, x), behavior: "smooth" })
            }
        }
    }

    // In Auto the banners arrive after the fetch, so the ceremony waits for
    // them; otherwise it would run on an empty rafters and mark itself done.
    const classKey = list.map((c) => `${c.name}:${c.status}`).join("|")
    useEffect(() => {
        if (skip || !ready) return
        if (inView) ceremony()
        else if (replayOnReenter) reset()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [inView, skip, ready, classKey])

    // On the Framer canvas, show the finished state centered on this week's class
    useEffect(() => {
        if (skip && newIdx.length) centerOn((newIdx[0] + newIdx[newIdx.length - 1]) / 2, false)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [skip, h, w, slotWidth, classKey])

    // ---------- Art ----------
    const svgUrl = (svg: string) => `url("data:image/svg+xml,${encodeURIComponent(svg)}")`
    const trussBg = svgUrl(`<svg xmlns='http://www.w3.org/2000/svg' width='60' height='44'>
      <path d='M0 41 L30 4 L60 41' stroke='${trussColor}' stroke-opacity='.8' stroke-width='3.2' fill='none'/>
      <rect x='28.6' y='3' width='2.8' height='38' fill='${trussColor}' fill-opacity='.7'/>
      <rect y='0' width='60' height='6' fill='${trussColor}'/><rect y='0' width='60' height='1.5' fill='#fff' fill-opacity='.18'/>
      <rect y='38' width='60' height='6' fill='${trussColor}'/><rect y='38' width='60' height='1.2' fill='#fff' fill-opacity='.12'/>
      <circle cx='30' cy='3' r='1.6' fill='#fff' fill-opacity='.3'/></svg>`)
    const truss2Bg = svgUrl(`<svg xmlns='http://www.w3.org/2000/svg' width='30' height='22'>
      <path d='M0 20 L15 2 L30 20' stroke='${trussColor}' stroke-width='1.6' fill='none'/>
      <rect width='30' height='3' fill='${trussColor}'/><rect y='19' width='30' height='3' fill='${trussColor}'/></svg>`)
    const ropeBg = `repeating-linear-gradient(160deg, ${ropeColor} 0 2px, rgba(0,0,0,.35) 2px 4px), ${ropeColor}`
    const P = `fr${uid}`
    const dim = Math.max(0, 1 - dimAmount)

    const css = `
    .${P} *{box-sizing:border-box}
    .${P} .fr-scroller{position:absolute;inset:0;overflow-x:auto;overflow-y:hidden;overscroll-behavior-x:contain;scrollbar-width:none;-webkit-overflow-scrolling:touch}
    .${P} .fr-scroller::-webkit-scrollbar{display:none}
    .${P} .fr-far,.${P} .fr-truss,.${P} .fr-slot{transition:filter .9s ease}
    .${P}.fr-dark .fr-far,.${P}.fr-dark .fr-truss{filter:brightness(${dim})}
    .${P}.fr-dark .fr-slot:not(.fr-lit){filter:brightness(${dim})}
    .${P}.fr-dark .fr-marquee{animation-play-state:paused}
    .${P} .fr-idle{transform-origin:50% 0;animation:${P}idle var(--dur) ease-in-out var(--delay) infinite}
    @keyframes ${P}idle{0%,100%{transform:rotate(calc(var(--amp) * -1))}50%{transform:rotate(var(--amp))}}
    .${P} .fr-marquee{display:flex;width:max-content;animation:${P}marquee 38s linear infinite}
    @keyframes ${P}marquee{to{transform:translateX(-50%)}}
    .${P} .fr-cone{opacity:0;transition:opacity .7s ease}
    .${P} .fr-lit .fr-cone{opacity:1}
    .${P} .fr-fresh .fr-cone{opacity:.42}
    .${P} .fr-newtag{opacity:0;transition:opacity .6s ease .2s}.${P} .fr-fresh .fr-newtag{opacity:1}
    .${P} .fr-sheen::before{content:"";position:absolute;top:-10%;bottom:-10%;width:60%;left:-80%;background:linear-gradient(100deg,transparent,rgba(255,255,255,.22),transparent);transform:skewX(-14deg)}
    .${P} .fr-arrive .fr-sheen::before{animation:${P}sheen 1.1s ease-out .05s both}
    .${P} .fr-arrive{animation:${P}flash 1.4s ease-out both}
    @keyframes ${P}sheen{to{left:130%}}
    @keyframes ${P}flash{0%{filter:drop-shadow(0 18px 22px rgba(0,0,0,.55)) brightness(1.5)}100%{filter:drop-shadow(0 18px 22px rgba(0,0,0,.55)) brightness(1)}}
    @media (prefers-reduced-motion: reduce){.${P} .fr-idle,.${P} .fr-marquee{animation:none}}
    `

    const idleVars = (i: number) =>
        ({
            "--dur": `${6 + ((i * 37) % 30) / 10}s`,
            "--delay": `${-((i * 53) % 80) / 10}s`,
            "--amp": `${idleSway * (0.7 + ((i * 29) % 6) / 10)}deg`,
        }) as React.CSSProperties

    const pulley = (x: number) => (
        <div style={{ position: "absolute", top: PULLEY_TOP, left: `calc(50% + ${x}px)`, width: 22, height: 22, marginLeft: -11, zIndex: 4 }}>
            <div style={{ position: "absolute", left: 2, right: 2, top: -2, height: 9, borderRadius: 2, background: trussColor, boxShadow: "inset 0 1px 0 rgba(255,255,255,.18)" }} />
            <div className="fr-wheel" style={{ position: "absolute", left: 3, top: 4, width: 16, height: 16, borderRadius: "50%",
                background: `radial-gradient(circle, #0c1314 0 2px, transparent 2.5px), conic-gradient(#596a6d 0 25%, #36443f 0 50%, #596a6d 0 75%, #36443f 0)`,
                boxShadow: "0 0 0 1.5px #1a2224" }} />
        </div>
    )

    const slotStyle = (i: number): React.CSSProperties => ({
        position: "absolute", top: 0, left: pad + i * slotWidth, width: slotWidth, height: arenaH,
    })

    const renderBanner = (c: Competitor, i: number) => {
        const isNew = c.status === "new"
        const lowered = isNew && (phase === "armed" || (phase === "running" && !arrived.has(i)))
        const fresh = isNew && phase === "done"
        const cls = ["fr-slot", lit.has(i) ? "fr-lit" : "", fresh ? "fr-fresh" : ""].join(" ")
        return (
            <div key={`c${i}`} className={cls} style={slotStyle(i)} ref={(el) => { slotRefs.current[i] = el }}>
                <div className="fr-cone" style={{ position: "absolute", top: -30, left: "50%", width: 520, height: 700, transform: "translateX(-50%)", pointerEvents: "none",
                    background: `conic-gradient(from 165deg at 50% 0%, transparent 0deg, ${spotColor} 8deg, ${spotColor} 22deg, transparent 30deg, transparent 360deg)`,
                    WebkitMaskImage: "linear-gradient(180deg,#000 40%,transparent 96%)", maskImage: "linear-gradient(180deg,#000 40%,transparent 96%)", mixBlendMode: "screen" }} />
                {pulley(-ROPE_OFFSET)}
                {pulley(ROPE_OFFSET)}
                <div style={{ position: "absolute", top: CLIP_TOP, left: -30, right: -30, bottom: -800, overflow: "hidden", zIndex: 1 }}>
                    <div className="fr-idle" style={idleVars(i)}>
                        <div className="fr-swing" style={{ transformOrigin: "50% 0" }}>
                            <div className="fr-lift" style={{ position: "relative", width: LIFT_W, margin: `${ROPE_VISIBLE}px auto 0`, transform: lowered ? `translateY(${DROP}px)` : undefined }}>
                                <div style={{ position: "absolute", left: 0, right: 0, bottom: "100%", height: 1000, pointerEvents: "none" }}>
                                    <i style={{ position: "absolute", bottom: 0, left: 28, width: 3, height: "100%", background: ropeBg, borderRadius: 2 }} />
                                    <i style={{ position: "absolute", bottom: 0, right: 28, width: 3, height: "100%", background: ropeBg, borderRadius: 2 }} />
                                </div>
                                {rod(trimColor)}
                                <Banner key={`b${arriveKey[i] || 0}`} c={c} arriving={!!arriveKey[i]} dimmed={!isNew} props={props} />
                            </div>
                        </div>
                    </div>
                </div>
                {isNew && showNewTag && (
                    <div className="fr-newtag" style={{ position: "absolute", left: "50%", top: tagTop, height: NEWTAG_H, transform: "translateX(-50%)", zIndex: 3, whiteSpace: "nowrap",
                        background: tagColor, color: tagTextColor, padding: "4px 9px 3px", borderRadius: 3, textTransform: "uppercase",
                        fontSize: 11, letterSpacing: "0.2em", fontWeight: 700, ...labelFont }}>
                        {newTagText}
                    </div>
                )}
            </div>
        )
    }

    const renderHook = (i: number, label: string, key: string) => (
        <div key={key} className="fr-slot" style={slotStyle(i)}>
            {pulley(0)}
            <div style={{ position: "absolute", top: CLIP_TOP, left: -30, right: -30, bottom: -800, overflow: "hidden", zIndex: 1 }}>
                <div className="fr-idle" style={idleVars(i)}>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                        <div style={{ width: 3, height: 70, background: ropeBg, opacity: 0.8 }} />
                        <svg viewBox="0 0 22 30" width={22} height={30} style={{ marginTop: -2 }} aria-hidden>
                            <path d="M11 0v14a7 7 0 1 1-7-7" fill="none" stroke={trimColor} strokeWidth={2.6} strokeLinecap="round" />
                        </svg>
                        <div style={{ marginTop: 6, color: textColor, opacity: 0.7, background: "rgba(0,0,0,.35)", border: `1px dashed ${trimColor}55`,
                            padding: "5px 9px 4px", borderRadius: 3, transform: "rotate(-3deg)", maxWidth: 150, textAlign: "center", lineHeight: 1.3,
                            textTransform: "uppercase", fontSize: 11, letterSpacing: "0.2em", fontWeight: 600, ...labelFont }}>
                            {label}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )

    const fade = `${edgeFade}%`
    return (
        <div ref={rootRef} className={`${P} ${dark ? "fr-dark" : ""}`}
            style={{ ...style, position: "relative", width: "100%", height: "100%", overflow: "hidden", borderRadius: cornerRadius,
                background: `radial-gradient(90% 60% at 50% 0%, ${bgTop} 0%, transparent 70%), linear-gradient(180deg, ${bgTop} 0%, ${bgBottom} 100%)` }}>
            <style>{css}</style>
            {auto && !rafters && (
                <div role="status" style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
                    textAlign: "center", zIndex: 3, color: textColor, opacity: 0.7, fontSize: 13, letterSpacing: "0.08em", ...labelFont }}>
                    {fetched.error || "Loading..."}
                </div>
            )}
            <div ref={scrollerRef} className="fr-scroller" tabIndex={0} aria-label="The rafters. Scroll to look across."
                style={{ WebkitMaskImage: `linear-gradient(90deg, transparent 0, #000 ${fade}, #000 calc(100% - ${fade}), transparent 100%)`,
                    maskImage: `linear-gradient(90deg, transparent 0, #000 ${fade}, #000 calc(100% - ${fade}), transparent 100%)` }}>
                <div style={{ position: "relative", width: trackW * s, height: arenaH * s }}>
                    <div style={{ position: "absolute", left: 0, top: 0, width: trackW, height: arenaH, transform: `scale(${s})`, transformOrigin: "0 0" }}>
                        {/* Far layer */}
                        <div ref={farRef} className="fr-far" style={{ position: "absolute", inset: 0, zIndex: 0, willChange: "transform" }}>
                            <div style={{ position: "absolute", left: 0, right: 0, top: 128, height: 22, opacity: 0.32, backgroundImage: truss2Bg, backgroundSize: "30px 22px" }} />
                            <div style={{ position: "absolute", left: 0, right: 0, top: 152, height: 10, opacity: 0.7,
                                background: `radial-gradient(circle at 50% 50%, rgba(255,240,205,.9) 0 1.6px, rgba(255,240,205,.18) 2.5px, transparent 6px) 0 0 / 90px 10px repeat-x` }} />
                            <div style={{ position: "absolute", left: 0, right: 0, top: 400, height: 150,
                                background: "repeating-linear-gradient(180deg, rgba(255,255,255,.035) 0 1px, transparent 1px 9px)",
                                WebkitMaskImage: "linear-gradient(180deg, transparent, #000 40%)", maskImage: "linear-gradient(180deg, transparent, #000 40%)" }} />
                            {showRibbon && (
                                <div style={{ position: "absolute", left: 0, right: 0, top: ribbonTop, height: RIBBON_H - 4, overflow: "hidden", background: "#020606", borderTop: "2px solid #1b2527", borderBottom: "2px solid #1b2527" }}>
                                    <div className="fr-marquee">
                                        {[0, 1].map((k) => (
                                            <span key={k} style={{ letterSpacing: "0.14em", fontWeight: 700, textTransform: "uppercase", whiteSpace: "nowrap",
                                                paddingRight: 60, ...labelFont, fontSize: 20, lineHeight: "26px", color: ledColor, textShadow: `0 0 8px ${ledColor}` }}>
                                                {ribbon}
                                            </span>
                                        ))}
                                    </div>
                                    <div style={{ position: "absolute", inset: 0, pointerEvents: "none", background: "radial-gradient(circle, transparent 0 0.9px, rgba(2,6,6,.78) 1.3px) 0 0 / 3px 3px" }} />
                                </div>
                            )}
                        </div>
                        {/* Main truss */}
                        <div ref={trussRef} className="fr-truss" style={{ position: "absolute", left: 0, right: 0, top: TRUSS_TOP, height: TRUSS_H, zIndex: 1,
                            backgroundImage: trussBg, backgroundSize: "60px 44px", filter: "drop-shadow(0 6px 8px rgba(0,0,0,.55))" }} />
                        {/* Slots */}
                        <div style={{ position: "absolute", inset: 0, zIndex: 2 }}>
                            {list.map((c, i) => renderBanner(c, i))}
                            {Array.from({ length: hooks }, (_, k) => renderHook(list.length + k, reservedLabel, `h${k}`))}
                            {showChampionHook && renderHook(list.length + hooks, championLabel, "champ")}
                        </div>
                        <canvas ref={canvasRef} style={{ position: "absolute", left: 0, top: 0, width: trackW, height: arenaH, zIndex: 5, pointerEvents: "none" }} />
                    </div>
                </div>
            </div>
        </div>
    )

    // ---------- Inner pieces ----------
    function rod(trim: string) {
        const cap: React.CSSProperties = { position: "absolute", top: -2, width: 13, height: 13, borderRadius: "50%",
            background: `radial-gradient(circle at 35% 35%, #ffffff, ${trim} 60%, #5a6668)` }
        return (
            <div style={{ position: "relative", height: 9, borderRadius: 5, zIndex: 2, background: `linear-gradient(180deg, #ffffff, ${trim} 55%, #6f7b7d)`, boxShadow: "0 2px 3px rgba(0,0,0,.5)" }}>
                <div style={{ ...cap, left: -5 }} />
                <div style={{ ...cap, right: -5 }} />
            </div>
        )
    }
}

function Banner({ c, arriving, dimmed, props }: { c: Competitor; arriving: boolean; dimmed: boolean; props: any }) {
    const id = useId().replace(/:/g, "")
    const {
        seasonLabel, eliminatedLabel, peakLabel, picksSuffix, showPhoto, grayscalePhotos,
        bannerColor, bannerEdge, trimColor, stripeColor, textColor, numberTop, numberBottom,
        nameFont, numberFont, labelFont, pastBrightness, showStripe, showTassel, arrivalShine, spacing,
    } = props
    const gap = { ...SPACING, ...(spacing || {}) }
    const baseFilter = "drop-shadow(0 18px 22px rgba(0,0,0,.55))"
    const variant = photoVariant(c.name)
    return (
        <article className={arriving && arrivalShine ? "fr-arrive" : ""} aria-label={`${c.name}, eliminated week ${c.week}`}
            style={{ position: "relative", width: BANNER_W, height: BANNER_H, margin: "-3px auto 0", filter: dimmed ? `${baseFilter} brightness(${pastBrightness})` : baseFilter }}>
            <svg viewBox={`0 0 ${BANNER_W} ${BANNER_H}`} width={BANNER_W} height={BANNER_H} style={{ position: "absolute", inset: 0 }} aria-hidden>
                <defs>
                    <linearGradient id={`fab${id}`} x1="0" x2="1">
                        <stop offset="0" stopColor={bannerEdge} /><stop offset=".16" stopColor={bannerColor} stopOpacity=".92" />
                        <stop offset=".5" stopColor={bannerColor} /><stop offset=".84" stopColor={bannerColor} stopOpacity=".92" /><stop offset="1" stopColor={bannerEdge} />
                    </linearGradient>
                    <linearGradient id={`top${id}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0" stopColor="#000" stopOpacity=".5" /><stop offset=".07" stopColor="#000" stopOpacity="0" />
                        <stop offset=".8" stopColor="#000" stopOpacity="0" /><stop offset="1" stopColor="#000" stopOpacity=".25" />
                    </linearGradient>
                    <linearGradient id={`fold${id}`} x1="0" x2="1">
                        <stop offset="0" stopColor="#000" stopOpacity="0" /><stop offset=".3" stopColor="#000" stopOpacity=".12" />
                        <stop offset=".36" stopColor="#fff" stopOpacity=".05" /><stop offset=".7" stopColor="#000" stopOpacity="0" />
                        <stop offset=".74" stopColor="#000" stopOpacity=".1" /><stop offset=".8" stopColor="#fff" stopOpacity=".04" /><stop offset="1" stopColor="#000" stopOpacity="0" />
                    </linearGradient>
                    <pattern id={`wv${id}`} width="3" height="3" patternUnits="userSpaceOnUse">
                        <rect width="1" height="3" fill="#fff" opacity=".035" /><rect width="3" height="1" fill="#000" opacity=".05" />
                    </pattern>
                    <clipPath id={`cp${id}`}><polygon points="0,0 196,0 196,370 98,412 0,370" /></clipPath>
                </defs>
                <rect width="196" height="412" fill={bannerEdge} clipPath={`url(#cp${id})`} />
                <g clipPath={`url(#cp${id})`}>
                    <rect width="196" height="432" fill={`url(#fab${id})`} />
                    <rect width="196" height="432" fill={`url(#wv${id})`} />
                    <rect width="196" height="432" fill={`url(#fold${id})`} />
                    {showStripe && <rect y="349" width="196" height="7" fill={stripeColor} />}
                    {showStripe && <rect y="359" width="196" height="2" fill={trimColor} opacity=".85" />}
                    <rect width="196" height="432" fill={`url(#top${id})`} />
                </g>
                <polygon points="7,7 189,7 189,365.5 98,404 7,365.5" fill="none" stroke={trimColor} strokeWidth="1.5" />
                <polygon points="11.5,11.5 184.5,11.5 184.5,362.5 98,399 11.5,362.5" fill="none" stroke={trimColor} strokeWidth=".7" opacity=".5" />
                {showTassel && <line x1="98" y1="411" x2="98" y2="421" stroke={trimColor} strokeWidth="1.6" />}
                {showTassel && <ellipse cx="98" cy="425" rx="3.6" ry="6" fill={trimColor} />}
            </svg>
            <div className="fr-sheen" style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden", clipPath: "polygon(0 0,100% 0,100% 85.6%,50% 95.4%,0 85.6%)" }} />
            <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 345, padding: `${gap.top}px 20px 0`, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", color: textColor }}>
                <span style={{ fontSize: 11, letterSpacing: "0.3em", fontWeight: 700, textTransform: "uppercase", color: trimColor, paddingLeft: "0.3em", ...labelFont }}>{seasonLabel}</span>
                {showPhoto && (
                    <div style={{ width: 54, height: 54, borderRadius: "50%", overflow: "hidden", marginTop: gap.seasonToPhoto, flexShrink: 0,
                        boxShadow: `0 0 0 2px ${bannerEdge}, 0 0 0 3.5px ${trimColor}, 0 4px 8px rgba(0,0,0,.4)`, filter: grayscalePhotos ? "grayscale(1)" : undefined,
                        background: "radial-gradient(circle at 40% 30%, #a3acad, #596264)" }}>
                        {c.photo?.src ? (
                            <img src={c.photo.src} srcSet={c.photo.srcSet} alt={c.photo.alt || c.name} style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
                        ) : variant ? (
                            <ProfilePictures variant={variant} style={{ width: "100%", height: "100%" }} />
                        ) : (
                            <svg viewBox="0 0 64 64" width="100%" height="100%" aria-hidden>
                                <circle cx="32" cy="25" r="11" fill="#3f4749" /><path d="M8 66c2-14 12-21 24-21s22 7 24 21z" fill="#3f4749" />
                            </svg>
                        )}
                    </div>
                )}
                <div style={{ fontSize: 34, lineHeight: 0.9, fontWeight: 900, letterSpacing: "0.02em", textTransform: "uppercase", marginTop: showPhoto ? gap.photoToName : gap.seasonToPhoto,
                    textShadow: "0 1px 0 rgba(0,0,0,.55)", whiteSpace: "nowrap", ...nameFont, color: textColor }}>{c.name}</div>
                <span style={{ fontSize: 94, lineHeight: 0.8, fontWeight: 900, paddingTop: 6, marginTop: gap.nameToNumber, fontVariantNumeric: "tabular-nums", ...numberFont,
                    background: `linear-gradient(180deg, ${numberTop} 0%, ${numberBottom} 100%)`, WebkitBackgroundClip: "text", backgroundClip: "text",
                    color: "transparent", filter: `drop-shadow(0 3px 0 ${bannerEdge}) drop-shadow(0 0 1px rgba(0,0,0,.6))` }}>{c.week}</span>
                <div style={{ fontSize: 11, letterSpacing: "0.24em", fontWeight: 600, textTransform: "uppercase", color: trimColor, opacity: 0.85, marginTop: gap.numberToLabel, paddingLeft: "0.24em", ...labelFont }}>{eliminatedLabel}</div>
                <div style={{ width: 44, height: 1, flexShrink: 0, background: `linear-gradient(90deg, transparent, ${trimColor}, transparent)`, margin: `${gap.labelToRule}px 0 ${gap.ruleToStats}px` }} />
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: gap.betweenStats, fontWeight: 500, color: trimColor, fontVariantNumeric: "tabular-nums", ...labelFont, fontSize: 13.5, lineHeight: 1.2 }}>
                    <span>{peakLabel} {c.peak}</span>
                    <span>{c.picks} {picksSuffix}</span>
                </div>
            </div>
        </article>
    )
}

// ---------- Property controls ----------
const fontControl = (title: string, size: number, extra: any = {}) => ({
    type: ControlType.Font,
    title,
    controls: "extended",
    defaultFontType: "sans-serif",
    defaultValue: { fontSize: size, ...extra },
})

addPropertyControls(FEPRafters, {
    source: {
        type: ControlType.Enum,
        title: "Source",
        options: ["manual", "auto"],
        optionTitles: ["Manual", "Auto (JSON)"],
        defaultValue: "manual",
        description: "Manual takes the banners from the Competitors list. Auto reads them out of the week file.",
    },
    year: {
        type: ControlType.Number, title: "Year", defaultValue: 2026, min: 2016, max: 2100, step: 1, displayStepper: true,
        description: "The season. Also the default season label.",
    },
    week: {
        type: ControlType.Number, title: "Week", defaultValue: 1, min: 0, max: 18, step: 1, displayStepper: true,
        description: "Bind to the newsletter's week.",
        hidden: (p: any) => p.source !== "auto",
    },
    baseUrl: {
        type: ControlType.String,
        title: "Data base URL",
        defaultValue: "https://raw.githubusercontent.com/jleibowitz9/fep/main/chart-data",
        placeholder: "https://raw.githubusercontent.com/.../chart-data",
        description: "The folder holding the year folders. Loads {baseUrl}/{year}/week-NN.json.",
        hidden: (p: any) => p.source !== "auto",
    },
    competitors: {
        type: ControlType.Array,
        title: "Competitors",
        hidden: (p: any) => p.source === "auto",
        control: {
            type: ControlType.Object,
            controls: {
                name: { type: ControlType.String, title: "Name", defaultValue: "Name" },
                status: { type: ControlType.Enum, title: "Status", options: ["past", "new"], optionTitles: ["Earlier week", "This week"], displaySegmentedControl: true, defaultValue: "new" },
                photo: { type: ControlType.ResponsiveImage, title: "Photo" },
                week: { type: ControlType.Number, title: "Week out", defaultValue: 6, min: 1, max: 18, step: 1, displayStepper: true },
                peak: { type: ControlType.String, title: "Peak odds", defaultValue: "0.0%" },
                picks: { type: ControlType.String, title: "Picks", defaultValue: "0 of 0" },
            },
        },
        defaultValue: [
            { name: "Andy", status: "past", week: 3, peak: "4.1%", picks: "1 of 3" },
            { name: "Pop", status: "past", week: 4, peak: "6.0%", picks: "2 of 4" },
            { name: "Jay", status: "past", week: 5, peak: "11.7%", picks: "3 of 5" },
            { name: "Sarah", status: "new", week: 6, peak: "14.2%", picks: "4 of 6" },
            { name: "Amir", status: "new", week: 6, peak: "22.6%", picks: "4 of 6" },
            { name: "Marsha", status: "new", week: 6, peak: "31.0%", picks: "3 of 6" },
        ],
    },
    emptyHooks: { type: ControlType.Number, title: "Empty Hooks", defaultValue: 5, min: 0, max: 12, step: 1, displayStepper: true, hidden: (p: any) => p.source === "auto" },
    showChampionHook: { type: ControlType.Boolean, title: "Champion Hook", defaultValue: true, hidden: (p: any) => p.source === "auto" },

    // Text
    seasonLabel: { type: ControlType.String, title: "Season Label", defaultValue: "", placeholder: "FEP {year}", description: "Leave empty for FEP and the Year." },
    eliminatedLabel: { type: ControlType.String, title: "Eliminated Label", defaultValue: "Week eliminated" },
    peakLabel: { type: ControlType.String, title: "Peak Label", defaultValue: "Peak" },
    picksSuffix: { type: ControlType.String, title: "Picks Suffix", defaultValue: "right" },
    showNewTag: { type: ControlType.Boolean, title: "New Tag", defaultValue: true },
    newTagText: { type: ControlType.String, title: "New Tag Text", defaultValue: "Eliminated this week", hidden: (p: any) => !p.showNewTag },
    reservedLabel: { type: ControlType.String, title: "Hook Label", defaultValue: "Reserved" },
    championLabel: { type: ControlType.String, title: "Champion Label", defaultValue: "Champion's hook. Always empty.", hidden: (p: any) => !p.showChampionHook },
    showRibbon: { type: ControlType.Boolean, title: "Ribbon Board", defaultValue: true },
    ribbonText: {
        type: ControlType.String, title: "Ribbon Text", displayTextArea: true,
        defaultValue: "Eliminated this week: {names}   ●   {season}   ●   {alive} still alive   ●   Go Birds   ●   ",
        description: "{names} = this week's eliminations. {alive} = empty hooks plus champion hook. {season} = the season label.",
        hidden: (p: any) => !p.showRibbon,
    },
    showPhoto: { type: ControlType.Boolean, title: "Photos", defaultValue: true, description: "From the Profile Pictures component, matched by first name." },
    grayscalePhotos: { type: ControlType.Boolean, title: "Grayscale", defaultValue: true, hidden: (p: any) => !p.showPhoto },

    // Colors
    bgTop: { type: ControlType.Color, title: "Arena Top", defaultValue: "#13252A" },
    bgBottom: { type: ControlType.Color, title: "Arena Bottom", defaultValue: "#050B0C" },
    bannerColor: { type: ControlType.Color, title: "Banner", defaultValue: "#33464A" },
    bannerEdge: { type: ControlType.Color, title: "Banner Shadow", defaultValue: "#1C2729" },
    trimColor: { type: ControlType.Color, title: "Trim", defaultValue: "#A9B3B5" },
    stripeColor: { type: ControlType.Color, title: "Stripe", defaultValue: "#566468" },
    textColor: { type: ControlType.Color, title: "Text", defaultValue: "#E4E9EA" },
    numberTop: { type: ControlType.Color, title: "Number Top", defaultValue: "#B9C2C4" },
    numberBottom: { type: ControlType.Color, title: "Number Bottom", defaultValue: "#7C898B" },
    ropeColor: { type: ControlType.Color, title: "Rope", defaultValue: "#CDBF9C" },
    trussColor: { type: ControlType.Color, title: "Truss", defaultValue: "#3A484B" },
    ledColor: { type: ControlType.Color, title: "Ribbon LED", defaultValue: "#E3A857" },
    spotColor: { type: ControlType.Color, title: "Spotlight", defaultValue: "rgba(255, 244, 214, 0.1)" },
    tagColor: { type: ControlType.Color, title: "Tag Fill", defaultValue: "#C4CCCE" },
    tagTextColor: { type: ControlType.Color, title: "Tag Text", defaultValue: "#081113" },

    // Fonts
    nameFont: fontControl("Name Font", 34),
    numberFont: fontControl("Number Font", 94),
    labelFont: fontControl("Label Font", 11),

    // Motion
    trigger: { type: ControlType.Number, title: "Play When Visible", defaultValue: 50, min: 5, max: 100, step: 5, unit: "%" },
    replayOnReenter: { type: ControlType.Boolean, title: "Replay On Return", defaultValue: false },
    autoPan: { type: ControlType.Boolean, title: "Auto Pan", defaultValue: true },
    hoistDuration: { type: ControlType.Number, title: "Hoist Time", defaultValue: 3.6, min: 1, max: 8, step: 0.1, unit: "s" },
    gapBetween: { type: ControlType.Number, title: "Gap Between", defaultValue: 0.9, min: 0, max: 4, step: 0.1, unit: "s" },
    settleSwing: { type: ControlType.Number, title: "Settle Swing", defaultValue: 2.4, min: 0, max: 8, step: 0.1, unit: "°" },
    idleSway: { type: ControlType.Number, title: "Idle Sway", defaultValue: 0.45, min: 0, max: 3, step: 0.05, unit: "°" },
    dimAmount: { type: ControlType.Number, title: "Lights Dim", defaultValue: 0.7, min: 0, max: 0.95, step: 0.05 },
    pastBrightness: { type: ControlType.Number, title: "Past Brightness", defaultValue: 0.78, min: 0.3, max: 1, step: 0.02 },
    dust: { type: ControlType.Number, title: "Dust", defaultValue: 1, min: 0, max: 3, step: 0.1 },
    parallax: { type: ControlType.Number, title: "Depth", defaultValue: 0.42, min: 0, max: 0.9, step: 0.02 },
    reducedMotionSafe: { type: ControlType.Boolean, title: "Respect Reduced Motion", defaultValue: true },
    arrivalShine: { type: ControlType.Boolean, title: "Arrival Shine", defaultValue: false, description: "A sheen and flash as each banner reaches the truss. Off, since nobody is celebrating." },

    // Layout
    slotWidth: { type: ControlType.Number, title: "Banner Spacing", defaultValue: 236, min: 200, max: 400, step: 2 },
    edgePadding: { type: ControlType.Number, title: "Edge Padding", defaultValue: 180, min: 0, max: 600, step: 10 },
    edgeFade: { type: ControlType.Number, title: "Edge Fade", defaultValue: 7, min: 0, max: 25, step: 1, unit: "%" },
    cornerRadius: { type: ControlType.Number, title: "Radius", defaultValue: 8, min: 0, max: 48 },
    showStripe: { type: ControlType.Boolean, title: "Stripe", defaultValue: true },
    showTassel: { type: ControlType.Boolean, title: "Tassel", defaultValue: true },

    // Spacing
    spacing: {
        type: ControlType.Object,
        title: "Spacing",
        controls: {
            top: { type: ControlType.Number, title: "Top", defaultValue: 24, min: 0, max: 80, step: 1, unit: "px" },
            seasonToPhoto: { type: ControlType.Number, title: "Season → Photo", defaultValue: 12, min: 0, max: 60, step: 1, unit: "px" },
            photoToName: { type: ControlType.Number, title: "Photo → Name", defaultValue: 14, min: 0, max: 60, step: 1, unit: "px" },
            nameToNumber: { type: ControlType.Number, title: "Name → Week", defaultValue: 10, min: -20, max: 60, step: 1, unit: "px" },
            numberToLabel: { type: ControlType.Number, title: "Week → Label", defaultValue: 8, min: -20, max: 60, step: 1, unit: "px" },
            labelToRule: { type: ControlType.Number, title: "Label → Rule", defaultValue: 12, min: 0, max: 60, step: 1, unit: "px" },
            ruleToStats: { type: ControlType.Number, title: "Rule → Stats", defaultValue: 12, min: 0, max: 60, step: 1, unit: "px" },
            betweenStats: { type: ControlType.Number, title: "Between Stats", defaultValue: 4, min: 0, max: 40, step: 1, unit: "px" },
            bannerToBadge: { type: ControlType.Number, title: "Banner → Badge", defaultValue: 14, min: 0, max: 80, step: 1, unit: "px" },
            badgeToTicker: { type: ControlType.Number, title: "Badge → Ticker", defaultValue: 24, min: 0, max: 80, step: 1, unit: "px" },
            tickerToBottom: { type: ControlType.Number, title: "Ticker → Bottom", defaultValue: 22, min: 0, max: 80, step: 1, unit: "px" },
        },
    },
})
