# Test fixtures

Frozen copies of what the family actually saw, kept here so the regression
tests compare against a fixed artifact rather than a file someone might edit.

| File | What it is |
|---|---|
| `simulator_2025.py` | Jacob's 2025 simulator, exactly as it ran that season. `tests/test_engine.py` executes it and requires the current engine to reproduce its week-by-week board. |

It used to be read from `../2025/simulator.py`, outside the repo. Two problems:
a checkout anywhere else could not run the most important test in the suite,
and editing that file would silently change what "no regression" means. A
regression fixture has to be frozen to be worth anything.

Do not edit these. If the 2025 board is ever genuinely wrong, that is a new
finding to record, not a fixture to adjust.
