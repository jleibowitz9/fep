// Style a scroll section's scrollbar, or hide it.
//
// HOW TO USE
//   1. Framer > Assets > Code > New File, name it Scrollbar, paste this.
//   2. Select the scrolling layer on the canvas.
//   3. Properties > Code Overrides > File: Scrollbar,
//      Override: withStyledScrollbar   (or withHiddenScrollbar)
//
// Scoped to the layer it is applied to and everything inside it, so no other
// scrollbar on the site is touched. The usual advice is a rule in Site
// Settings, which also strips the scrollbar from long pages where it is the
// only sign of how far through you are.
//
// HOW THE RELATIVE WIDTH WORKS
//
// A scrollbar pseudo-element takes a pixel margin and nothing else. Tested side
// by side in Chrome:
//
//   margin: 0 40px                      inset at both ends          works
//   margin: 0 15%                       ignored, runs edge to edge
//   margin: 0 calc((100% - 400px) / 2)  ignored, runs edge to edge
//
// So a relative width cannot be written in the CSS. It can be computed: watch
// the row and rewrite the pixel margin whenever its width changes. The bar then
// holds the same fraction of the row at every breakpoint, and it is still the
// browser's own scrollbar, so dragging it, clicking the track, shift-scrolling
// and the platform's own behaviour all keep working. A hand-drawn div would
// have to reimplement every one of those.

import type { ComponentType } from "react"
import { useEffect, useId, useState } from "react"

// ---- the dial ------------------------------------------------------------
const TRACK_WIDTH = 0.6 // fraction of the row, centred. null = fixed inset
const TRACK_INSET = 40 // px from each end, used only when TRACK_WIDTH is null
const TRACK_HEIGHT = 8 // the whole bar
const PADDING = 2 // gap between track and fill, all round
const TRACK_COLOR = "rgba(255,255,255,0.10)"
const FILL_COLOR = "rgba(255,255,255,0.70)"
// --------------------------------------------------------------------------

// The fill is TRACK_HEIGHT minus PADDING top and bottom. Both are fully
// rounded, so the radii are derived rather than kept in step by hand.
const FILL_HEIGHT = TRACK_HEIGHT - PADDING * 2

const DEBUG_TRACK = "rgba(255,0,0,0.85)"
const DEBUG_FILL = "rgba(0,220,255,0.95)"

/**
 * Everything is !important. Framer injects its own stylesheet and the
 * override's <style> tag is not guaranteed to come after it, so without this a
 * single competing declaration wins silently.
 */
const rules = (id: string, track: string, fill: string, inset: number) => {
    const self = `[data-fep-bar="${id}"]`
    const any = `${self}, ${self} *`
    return `
/* Put the scrollbar back before styling it.
 *
 * A host stylesheet that hides scrollbars wins by default, because the rules
 * below only ever set a height: nothing here contradicts display:none or
 * scrollbar-width:none, so they stand and there is no bar to style. That is
 * exactly what a published Framer site does, which is why this worked on the
 * canvas and showed nothing at all on the site.
 *
 * scrollbar-width must be auto rather than thin: any other value disables
 * ::-webkit-scrollbar styling outright in Chrome. The Firefox block below
 * overrides it, and only Firefox ever sees that block. */
${any} {
  scrollbar-width: auto !important;
  -ms-overflow-style: auto !important;
}
/* Firefox only, and it has to be fenced off.
 *
 * scrollbar-width and scrollbar-color are the standard properties, and setting
 * either to anything other than auto DISABLES ::-webkit-scrollbar styling
 * outright in current Chrome. Declared unconditionally, as a well-meant
 * fallback, they silently threw away every rule below: the bar kept roughly the
 * right colours, because scrollbar-color was doing that part, while the height,
 * the radius, the padding and the inset were all quietly ignored.
 *
 * @supports asks whether the browser knows the pseudo-element at all, so
 * Firefox gets the approximation and Chrome and Safari never see these two. */
@supports not selector(::-webkit-scrollbar) {
  /* !important, and after the rule above, or the auto there wins here too. */
  ${any} {
    scrollbar-width: thin !important;
    scrollbar-color: ${fill} ${track} !important;
  }
}
${self}::-webkit-scrollbar, ${self} *::-webkit-scrollbar {
  display: block !important;
  -webkit-appearance: none !important;
  height: ${TRACK_HEIGHT}px !important;
  width: ${TRACK_HEIGHT}px !important;
}
${self}::-webkit-scrollbar-track, ${self} *::-webkit-scrollbar-track {
  background: ${track} !important;
  border-radius: ${TRACK_HEIGHT / 2}px !important;
  /* Holds the track back from both ends. This moves the range the thumb
     travels as well as the painted track, which is what makes it work. */
  margin: 0 ${inset}px !important;
}
${self}::-webkit-scrollbar-thumb, ${self} *::-webkit-scrollbar-thumb {
  background-color: ${fill} !important;
  border-radius: ${FILL_HEIGHT / 2}px !important;
  /* A transparent border plus content-box clipping is how you get padding on a
     scrollbar thumb: there is no padding property on this pseudo-element. */
  border: ${PADDING}px solid transparent !important;
  background-clip: content-box !important;
}
${self}::-webkit-scrollbar-corner, ${self} *::-webkit-scrollbar-corner {
  background: transparent !important;
}
`
}

/**
 * Find the element the browser is actually drawing a scrollbar on.
 *
 * Usually not the layer the override is applied to: Framer renders a wrapper
 * inside it and that wrapper is the one that scrolls. Rather than guess at the
 * markup, look for the first thing whose content is wider than its box.
 */
function findScroller(root: Element | null): Element | null {
    if (!root) return null
    if (root.scrollWidth > root.clientWidth + 1) return root
    const nodes = root.querySelectorAll("*")
    for (let i = 0; i < nodes.length; i++) {
        if (nodes[i].scrollWidth > nodes[i].clientWidth + 1) return nodes[i]
    }
    return null
}

function useInset(id: string): number {
    const [inset, setInset] = useState(
        TRACK_WIDTH == null ? TRACK_INSET : 0
    )

    useEffect(() => {
        if (TRACK_WIDTH == null) return
        const root = document.querySelector(`[data-fep-bar="${id}"]`)
        const measure = () => {
            const el = findScroller(root) || root
            const width = el ? el.clientWidth : 0
            if (!width) return
            setInset(Math.max(0, Math.round((width * (1 - TRACK_WIDTH)) / 2)))
        }
        measure()
        // Observe the root, not the scroller: the scroller may not exist on the
        // first pass, and this fires again once the layout settles.
        const observer = new ResizeObserver(measure)
        if (root) observer.observe(root)
        window.addEventListener("resize", measure)
        return () => {
            observer.disconnect()
            window.removeEventListener("resize", measure)
        }
    }, [id])

    return inset
}

// A unique attribute per instance, so two scrolling rows on one page do not
// measure each other.
const useBarId = () => "b" + useId().replace(/[^a-zA-Z0-9]/g, "")

export function withStyledScrollbar(Component): ComponentType {
    return (props) => {
        const id = useBarId()
        const inset = useInset(id)
        return (
            <>
                <style>{rules(id, TRACK_COLOR, FILL_COLOR, inset)}</style>
                <Component {...props} data-fep-bar={id} />
            </>
        )
    }
}

/**
 * Same geometry, unmissable colours. If the track is not red, no rule is
 * reaching the scrolling element at all. If it is red but runs edge to edge,
 * the rules are landing and only the margin is being refused.
 */
export function withScrollbarDebug(Component): ComponentType {
    return (props) => {
        const id = useBarId()
        const inset = useInset(id)
        return (
            <>
                <style>{rules(id, DEBUG_TRACK, DEBUG_FILL, inset)}</style>
                <Component {...props} data-fep-bar={id} />
            </>
        )
    }
}

const HIDDEN_CSS = `
[data-fep-nobar], [data-fep-nobar] * {
  scrollbar-width: none; -ms-overflow-style: none;
}
[data-fep-nobar]::-webkit-scrollbar,
[data-fep-nobar] *::-webkit-scrollbar { display: none; width: 0; height: 0; }
`

export function withHiddenScrollbar(Component): ComponentType {
    return (props) => (
        <>
            <style>{HIDDEN_CSS}</style>
            <Component {...props} data-fep-nobar="" />
        </>
    )
}
