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
| `TRACK_INSET` | held back 40px from each end |

### Two things worth knowing

**The inset works on the track, and the thumb respects it.** `margin` on
`::-webkit-scrollbar-track` moves both the painted track and the range the thumb
travels, so the bar reads as an element on the page rather than as the edge of
the window. Verified by rendering it against markers at the inset positions.

**The rules cover descendants.** The element that actually scrolls is usually a
wrapper Framer renders inside the layer you can select, so a rule aimed only at
the outer element silently does nothing. That is the usual reason this appears
not to work.

**Firefox gets an approximation.** It only exposes `scrollbar-width` and
`scrollbar-color`, so it gets `thin` and the two colours: no radius, no padding,
no inset. Chrome and Safari get the full treatment.
