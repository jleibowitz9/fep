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

const CSS = `
[data-fep-bar], [data-fep-bar] * {
  scrollbar-width: thin;                                   /* Firefox */
  scrollbar-color: ${FILL_COLOR} ${TRACK_COLOR};
}
[data-fep-bar]::-webkit-scrollbar,
[data-fep-bar] *::-webkit-scrollbar {
  height: ${TRACK_HEIGHT}px;
  width: ${TRACK_HEIGHT}px;
}
[data-fep-bar]::-webkit-scrollbar-track,
[data-fep-bar] *::-webkit-scrollbar-track {
  background: ${TRACK_COLOR};
  border-radius: ${TRACK_HEIGHT / 2}px;
  /* Holds the track back from both ends, so it reads as an element on the
     page rather than as the edge of the window. */
  margin: 0 ${TRACK_INSET}px;
}
[data-fep-bar]::-webkit-scrollbar-thumb,
[data-fep-bar] *::-webkit-scrollbar-thumb {
  background-color: ${FILL_COLOR};
  border-radius: ${FILL_HEIGHT / 2}px;
  /* A transparent border plus content-box clipping is how you get padding on
     a scrollbar thumb: there is no padding property on this pseudo-element. */
  border: ${PADDING}px solid transparent;
  background-clip: content-box;
}
[data-fep-bar]::-webkit-scrollbar-thumb:hover,
[data-fep-bar] *::-webkit-scrollbar-thumb:hover {
  background-color: rgba(255,255,255,0.85);
}
[data-fep-bar]::-webkit-scrollbar-corner,
[data-fep-bar] *::-webkit-scrollbar-corner { background: transparent; }
`

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

export function withHiddenScrollbar(Component): ComponentType {
    return (props) => (
        <>
            <style>{HIDDEN_CSS}</style>
            <Component {...props} data-fep-nobar="" />
        </>
    )
}
