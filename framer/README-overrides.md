# Code overrides

## HideScrollbar

Hides the scrollbar on a scrolling layer without stopping it scrolling.

1. **Assets > Code > New File**, name it `HideScrollbar`, paste
   `HideScrollbar.tsx`.
2. Select the scrolling layer.
3. **Properties > Code Overrides**: File `HideScrollbar`, Override
   `withHiddenScrollbar`.

Scoped to that layer and its contents, so every other scrollbar on the site is
left alone. The common alternative, a `::-webkit-scrollbar { display: none }`
rule in Site Settings, also strips the scrollbar from long pages where people
use it to see how far through they are.

**Check Framer's own setting first.** Select the scroll section and look for a
scrollbar toggle in the properties panel. If it is there, use it and skip this.

### Worth knowing before you hide it

A scrollbar is the main signal that a row scrolls at all. Once it is gone,
something else has to say so. The leaderboard row already does the right thing
by letting the next card peek in at the edge; a fade or a pair of arrows works
too. A row that looks like it ends at the sixth card is a row nobody scrolls.
