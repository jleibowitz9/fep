# Code overrides

## Scrollbar

Styles a scroll section's scrollbar, or hides it. Two overrides in one file:
`withStyledScrollbar` and `withHiddenScrollbar`.

1. **Assets > Code > New File**, name it `Scrollbar`, paste `Scrollbar.tsx`.
2. Select the scrolling layer.
3. **Properties > Code Overrides**: File `Scrollbar`, Override
   `withStyledScrollbar`.

Open `scrollbar-preview.html` in a browser first to see it. That file is
generated from the same constants the override uses, so it is what you will get.

### The dial

At the top of `Scrollbar.tsx`:

| | |
|---|---|
| `TRACK_HEIGHT` | the whole bar, 8px |
| `PADDING` | gap between track and fill, 2px all round, so the fill is 4px |
| `TRACK_COLOR` | 10% white |
| `FILL_COLOR` | 70% white |
| `TRACK_WIDTH` | the bar as a fraction of the row, `0.6` = 60%. `null` for a fixed inset |
| `TRACK_INSET` | px from each end, used only when `TRACK_WIDTH` is `null` |

### It has to put the scrollbar back first

A published Framer site hides scrollbars. Rules that only set a height do not
contradict `display: none` or `scrollbar-width: none`, so the host wins, there
is no bar, and nothing gets styled. This is why it looked right on the canvas
and showed nothing at all on the site.

So the override forces the bar back into existence before styling it:
`display: block`, `-webkit-appearance: none`, and `scrollbar-width: auto`.
Verified against a host stylesheet using `display: none`, `scrollbar-width:
none`, and both together at `!important`: the bar survives all three.

`scrollbar-width` has to be `auto` rather than `thin`, because any value other
than `auto` disables `::-webkit-scrollbar` styling in Chrome. The Firefox block
overrides it, and only Firefox ever sees that block.

### The relative width is computed, not declared

A scrollbar pseudo-element takes a pixel margin and nothing else. Tested in
Chrome: `margin: 0 40px` insets both ends, `margin: 0 15%` is ignored, and
`margin: 0 calc((100% - 400px) / 2)` is ignored. So the override measures the
row and rewrites the pixel margin whenever its width changes.

| row | inset | bar |
|---|---|---|
| 420px | 84px | 252px, 60% |
| 980px | 196px | 588px, 60% |
| 1400px | 280px | 840px, 60% |

It is still the browser's own scrollbar, so dragging it, clicking the track and
shift-scrolling keep working. A hand-drawn bar would have to reimplement each of
those.

### Two things worth knowing

**The inset works on the track, and the thumb respects it.** `margin` on
`::-webkit-scrollbar-track` moves both the painted track and the range the thumb
travels, so the bar reads as an element on the page rather than as the edge of
the window. Verified by rendering it against markers at the inset positions.

**The rules cover descendants.** The element that actually scrolls is usually a
wrapper Framer renders inside the layer you can select, so a rule aimed only at
the outer element silently does nothing. That is the usual reason this appears
not to work.

**Firefox gets an approximation, and it has to be fenced off.**
`scrollbar-width` and `scrollbar-color` are the standard properties, and setting
either to anything but `auto` **disables `::-webkit-scrollbar` styling outright
in Chrome**. Declared unconditionally as a fallback they threw away every other
rule: the bar kept roughly the right colours, because `scrollbar-color` was
doing that part, while the height, radius, padding and inset were silently
ignored. They now sit inside `@supports not selector(::-webkit-scrollbar)`, so
Firefox gets `thin` plus the two colours and Chrome never sees them.

That is worth remembering generally: a well-meant standard-properties fallback
next to `::-webkit-scrollbar` rules does not degrade gracefully, it takes over.
