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

import type { ComponentType } from "react"

// WHAT THE INSET CAN AND CANNOT BE
//
// Only a fixed pixel value. Tested side by side in Chrome:
//
//   margin: 0 40px                      inset, both ends            works
//   margin: 0 15%                       ignored, runs edge to edge
//   margin: 0 calc((100% - 400px) / 2)  ignored, runs edge to edge
//
// A scrollbar pseudo-element does not resolve percentages or calc against
// anything, so a relative inset or a fixed track width is not available. If the
// row needs a proportional inset it has to come from the layout instead: make
// the scrolling layer itself narrower than the section.

// ---- the dial ------------------------------------------------------------
const TRACK_HEIGHT = 8 // the whole bar
const PADDING = 2 // gap between track and fill, all round
const TRACK_COLOR = "rgba(255,255,255,0.10)"
const FILL_COLOR = "rgba(255,255,255,0.70)"
const TRACK_INSET = 40 // px held back from each end, so it does not run
// the full width of the scroll area
// --------------------------------------------------------------------------

// The fill is TRACK_HEIGHT minus PADDING top and bottom. Both are fully
// rounded, so the radius is half the height rather than a number to keep in
// step by hand.
const FILL_HEIGHT = TRACK_HEIGHT - PADDING * 2

// Everything is !important. Framer injects its own stylesheet and the
// override's <style> tag is not guaranteed to come after it, so without this a
// single competing declaration wins silently and only some of the rules appear
// to work.
const rules = (attr: string, track: string, fill: string) => `
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
  [data-${attr}], [data-${attr}] * {
    scrollbar-width: thin;
    scrollbar-color: ${fill} ${track};
  }
}
[data-${attr}]::-webkit-scrollbar,
[data-${attr}] *::-webkit-scrollbar {
  height: ${TRACK_HEIGHT}px !important;
  width: ${TRACK_HEIGHT}px !important;
}
[data-${attr}]::-webkit-scrollbar-track,
[data-${attr}] *::-webkit-scrollbar-track {
  background: ${track} !important;
  border-radius: ${TRACK_HEIGHT / 2}px !important;
  /* Holds the track back from both ends, so it reads as an element on the page
     rather than as the edge of the window. This moves the range the thumb
     travels as well as the painted track, which is what makes it work. */
  margin: 0 ${TRACK_INSET}px !important;
}
[data-${attr}]::-webkit-scrollbar-thumb,
[data-${attr}] *::-webkit-scrollbar-thumb {
  background-color: ${fill} !important;
  border-radius: ${FILL_HEIGHT / 2}px !important;
  /* A transparent border plus content-box clipping is how you get padding on a
     scrollbar thumb: there is no padding property on this pseudo-element. */
  border: ${PADDING}px solid transparent !important;
  background-clip: content-box !important;
}
[data-${attr}]::-webkit-scrollbar-corner,
[data-${attr}] *::-webkit-scrollbar-corner { background: transparent !important; }
`

const CSS = rules("fep-bar", TRACK_COLOR, FILL_COLOR)

// Same geometry, unmissable colours. If the track is not red, no rule is
// reaching the scrolling element at all. If it is red but runs edge to edge,
// the rules are landing and only the margin is being refused.
const DEBUG_CSS = rules("fep-bar", "rgba(255,0,0,0.85)", "rgba(0,220,255,0.95)")

const HIDDEN_CSS = `
[data-fep-nobar], [data-fep-nobar] * {
  scrollbar-width: none; -ms-overflow-style: none;
}
[data-fep-nobar]::-webkit-scrollbar,
[data-fep-nobar] *::-webkit-scrollbar { display: none; width: 0; height: 0; }
`

/**
 * The rules cover descendants as well as the layer itself, because the element
 * that actually scrolls is usually a wrapper Framer renders inside the layer
 * you can select, and targeting only the outer one silently does nothing.
 */
export function withStyledScrollbar(Component): ComponentType {
    return (props) => (
        <>
            <style>{CSS}</style>
            <Component {...props} data-fep-bar="" />
        </>
    )
}

/**
 * Temporary, for working out why the bar does not look right. Swap the override
 * on the layer to this one, look, then swap back.
 */
export function withScrollbarDebug(Component): ComponentType {
    return (props) => (
        <>
            <style>{DEBUG_CSS}</style>
            <Component {...props} data-fep-bar="" />
        </>
    )
}

export function withHiddenScrollbar(Component): ComponentType {
    return (props) => (
        <>
            <style>{HIDDEN_CSS}</style>
            <Component {...props} data-fep-nobar="" />
        </>
    )
}
