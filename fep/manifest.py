"""
What the last weekly run actually wrote.

WHY THIS EXISTS
---------------
Both launch paths used to archive a run by staging whole directories -- `data`,
`newsletters`, `chart-data`. That is fine right up until a second session is
part-way through something in one of them, at which point the weekly run
commits work that is not finished and not its own. `CLAUDE.md` says to stage
your own paths and never `git add -A`; staging three directories is the same
mistake wearing a hat.

The run is the only thing that knows which files it wrote, so it writes them
down. Everything that archives a run -- `dashboard/serve.py` and
`scripts/fep-week.command` -- reads this instead of guessing from directories.

It lives under `data/dashboard_cache/`, which is gitignored, because it is a
note about the last run rather than part of the season. If it is missing or
stale the callers fall back to the old directory-wide behaviour, so a run
started before this existed still archives.
"""

from __future__ import annotations

import json
import os
import time
from typing import List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "dashboard_cache", "last_run.json")


def write(week: int, paths: List[str], path: str = PATH) -> Optional[str]:
    """Record the run's outputs, as paths relative to the repository root.

    Best effort. A manifest that cannot be written is not a reason to fail a
    run that has already succeeded -- the caller falls back to staging the
    directories, which is what it did before.
    """
    relative = sorted({os.path.relpath(p, ROOT) for p in paths if p})
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"week": week, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "paths": relative}, fh, indent=2)
        return path
    except OSError:
        return None


def read(path: str = PATH) -> Optional[dict]:
    """The last run's manifest, or None if there isn't a usable one.

    A path recorded here that no longer exists is dropped rather than passed to
    git, so a manifest naming a file someone has since removed still archives
    everything else the run wrote.
    """
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("paths"), list):
        return None
    data["paths"] = [p for p in data["paths"]
                     if isinstance(p, str) and os.path.exists(os.path.join(ROOT, p))]
    return data or None
