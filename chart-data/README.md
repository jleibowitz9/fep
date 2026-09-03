# chart-data

One immutable JSON per week, fetched by the Framer chart component at
`{baseUrl}/week-NN.json`. `week-07.json` contains weeks 0 through 7 and
physically cannot contain week 8, which is what makes an old newsletter's chart
unable to drift.

## 2025

Reproduces the **published newsletter numbers exactly** (verified cell by cell
against the season's weekly record). Kept so the archive matches what the family
actually saw.

Note that these are not a re-run of the model. The 2025 simulator preserved only
the final set of ESPN weights, and the weights for unplayed games moved a lot
during the season (game 14 went from .475 to .632). Replaying 2025 today with
current ESPN numbers produces a board that differs by up to about 6 points. The
published figures are authoritative, so they are what is stored here.

From 2026 on this problem disappears: every snapshot stores the weights that
produced it, so any past week can be regenerated exactly.
