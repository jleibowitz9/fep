// Hide a scrollbar without disabling the scroll.
//
// Framer renders a scroll section as an element with `overflow: auto`, and the
// browser draws its own scrollbar there. `overflow: hidden` would remove the
// bar and the scrolling with it, which is not what is wanted: the row still has
// to scroll, it just should not show a grey track under the cards.
//
// So this hides the *chrome* and leaves the behaviour alone, in the three
// places browsers keep that setting.
//
// HOW TO USE
//   1. Framer > Assets > Code > New File, name it HideScrollbar, paste this.
//   2. Select the scrolling layer on the canvas.
//   3. Properties panel > Code Overrides > File: HideScrollbar,
//      Override: withHiddenScrollbar.
//
// It is scoped to the layer it is applied to and everything inside it, so no
// other scrollbar on the site is affected. That matters: the usual fix for this
// is a site-wide CSS rule in Site Settings, which also hides the scrollbar on
// long pages where people rely on it.

import type { ComponentType } from "react"

const CSS = `
[data-fep-noscroll],
[data-fep-noscroll] * {
  scrollbar-width: none;        /* Firefox */
  -ms-overflow-style: none;     /* old Edge */
}
[data-fep-noscroll]::-webkit-scrollbar,
[data-fep-noscroll] *::-webkit-scrollbar {
  display: none;                /* Chrome, Safari */
  width: 0;
  height: 0;
}
`

/**
 * Applied to the scrolling layer.
 *
 * The rule covers descendants as well as the layer itself, because the element
 * that actually scrolls is often a wrapper Framer renders inside the layer you
 * can select, and targeting only the outer one silently does nothing.
 */
export function withHiddenScrollbar(Component): ComponentType {
    return (props) => (
        <>
            <style>{CSS}</style>
            <Component {...props} data-fep-noscroll="" />
        </>
    )
}
