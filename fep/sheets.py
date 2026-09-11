"""
Write the seven CMS tables to the Google Sheet that Framer reads.

WHAT THIS USED TO ALSO DO
-------------------------
Until September 2026 this module had a second writer: weekly competitor
percentages into `B2:M20` of a `Weighted - MASTER` tab, guarded by a range
check, a header check and a service-account fallback. That tab fed the
standings on the site, and the per-week tabs beside it fed the chart.

Both readers are gone. The chart moved to the immutable `chart-data/*.json`
files, and the standings moved to the `standings` CMS table. Jacob confirmed
the MASTER tab is no longer read by anything, so the writer, its guard, its
row builders and the service-account transport were removed rather than kept
working: a second deployment to redeploy, a second health row to read, and a
second push to remember, all to feed a tab nobody opens.

The matching `B2:M20` op in `appsscript/Code.gs` outlived the Python writer
by a day, so that removing dead code would not force a redeploy on its own. It
went in `2026.09.10-a`, which needed one anyway: `writeTable` is now the only
op the deployment accepts, so nothing can write raw numbers into any tab.

AUTHENTICATION
--------------
An Apps Script web app that lives inside the spreadsheet itself
(`appsscript/Code.gs`). No Google Cloud project, no service account, no key
file.

That is not just simpler, it is necessary: service account key creation is
blocked on Jacob's account by the `iam.disableServiceAccountKeyCreation`
organization policy. An Apps Script deployment runs as him and is not subject
to it.

The deployment URL and token live in `credentials/appsscript.json`, which is
gitignored. The URL alone is enough to reach the script, so the token is a
second factor, and the script itself refuses to write to any tab outside the
seven CMS tables.

`fep/cms.py` builds the tables and is pure: a season goes in, seven tables come
out, nothing is fetched or written. The transport is separate on purpose, so
swapping Sheets for Framer's Server API later changes one file.
"""

from __future__ import annotations

import csv
import os
import time
from typing import Dict, List, Optional, Sequence

CREDENTIALS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "credentials")


class SheetError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# the Apps Script path (the default)
# ---------------------------------------------------------------------------

APPSSCRIPT_CONFIG = os.path.join(CREDENTIALS_DIR, "appsscript.json")


def appsscript_available(config_path: str = APPSSCRIPT_CONFIG) -> bool:
    return os.path.exists(config_path)


def load_appsscript_config(config_path: str = APPSSCRIPT_CONFIG) -> dict:
    """The deployment this writes to.

    `cms_url` and `cms_token`, not `url` and `token`. The latter pair addressed
    the legacy spreadsheet, which nothing reads any more; a config that still
    carries them is fine and they are simply ignored.
    """
    import json
    if not os.path.exists(config_path):
        raise SheetError(
            "no Apps Script config at {}. See appsscript/README.md for the "
            "one-time setup.".format(config_path))
    with open(config_path) as fh:
        config = json.load(fh)
    for field in ("cms_url", "cms_token"):
        if not config.get(field):
            raise SheetError("{} is missing {!r}".format(config_path, field))
    if "/exec" not in config["cms_url"]:
        raise SheetError(
            "the Apps Script URL should end in /exec (a deployment), not /dev. "
            "got: {}".format(config["cms_url"]))
    return config


def new_token(length: int = 48) -> str:
    """A random shared secret for FEP_TOKEN."""
    import secrets
    return secrets.token_urlsafe(length)


def _call_appsscript(url: str, payload: dict, timeout: float = 60.0) -> dict:
    import json
    import urllib.error
    import urllib.request

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})
    try:
        # Apps Script answers a POST with a 302 to script.googleusercontent.com
        # and serves the body from there. urllib follows it by default, which is
        # exactly what is wanted here.
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise SheetError("Apps Script returned HTTP {}: {}".format(
            exc.code, exc.read().decode("utf-8", "replace")[:400]))
    except urllib.error.URLError as exc:
        raise SheetError("could not reach the Apps Script deployment: {}".format(exc))

    try:
        result = json.loads(raw)
    except ValueError:
        # Almost always the sign-in page, which means the deployment is not set
        # to "Anyone with the link".
        hint = ("the deployment is not public. Redeploy with "
                "'Who has access: Anyone with the link'."
                if "<html" in raw.lower() else raw[:300])
        raise SheetError("Apps Script did not return JSON. {}".format(hint))

    if not result.get("ok"):
        raise SheetError("Apps Script refused the write: {}".format(
            result.get("error", result)))
    return result


# ---------------------------------------------------------------------------
# the CMS tables
# ---------------------------------------------------------------------------

# Mirrors TABLE_TABS in appsscript/Code.gs. Duplicated deliberately: the script
# enforces it too, because a guard that only exists on the caller is not a
# guard. This copy is here to fail fast with a clearer message.
TABLE_TABS = ["seasons", "competitors", "competitor_seasons", "games",
              "weeks", "picks", "standings"]


CODE_GS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "appsscript", "Code.gs")


def local_code_version(path: str = CODE_GS) -> Optional[str]:
    """The CODE_VERSION in this checkout's Code.gs."""
    import re
    if not os.path.exists(path):
        return None
    match = re.search(r"var CODE_VERSION = '([^']+)'", open(path).read())
    return match.group(1) if match else None


def deployed_code_version(url: str, timeout: float = 60.0,
                          attempts: int = 2) -> Optional[str]:
    """The CODE_VERSION the deployment is actually running.

    Tried more than once. An Apps Script web app that has not been called
    recently is cold and can take seconds to wake, and a single short attempt
    reports a perfectly healthy deployment as dead -- which is exactly what
    happened during the September review, and a check that cries wolf is a
    check that gets ignored.

    None means "did not answer, or answered without a version". The two are
    genuinely different and `deployment_health` tells them apart; this function
    is only asked for the version.
    """
    return _probe(url, timeout=timeout, attempts=attempts)[0]


def _probe(url: str, timeout: float = 60.0, attempts: int = 2):
    """(version, error) from a deployment's health endpoint."""
    import json as _json
    import urllib.request
    error = None
    for attempt in range(max(1, attempts)):
        try:
            with urllib.request.urlopen(url + "?v=1", timeout=timeout) as response:
                body = _json.loads(response.read().decode()) or {}
            return body.get("version"), None
        except Exception as exc:  # noqa: BLE001  any failure is "did not answer"
            error = "{}: {}".format(type(exc).__name__, exc)
    return None, error


def assert_deployment_current(url: str) -> None:
    """Refuse to push against a stale deployment.

    Editing Code.gs in the Apps Script editor does not redeploy it, and a web
    app serves the code from its deployed version. So the file in this
    repository and the code actually running can differ with no visible sign,
    which has happened twice: once silently rewriting rows a newer guard would
    have refused.
    """
    local = local_code_version()
    if local is None:
        return
    live = deployed_code_version(url)
    if live == local:
        return
    raise SheetError(
        "the deployment is running {} but this checkout is {}.\n"
        "  Editing Code.gs does not redeploy it. Paste appsscript/Code.gs into\n"
        "  the editor, save, then Deploy > Manage deployments > edit >\n"
        "  Version: New version.".format(
            "an older version (no version stamp)" if live is None else live,
            local))


def deployment_health(config_path: str = APPSSCRIPT_CONFIG,
                      timeout: float = 30.0) -> List[dict]:
    """What each configured deployment is actually running, right now.

    `appsscript_available()` answers a much smaller question -- is there a
    config file on this disk -- and the dashboard was reading that as
    "Apps Script ready". A credentials file says nothing about whether either
    deployment answers, or whether it is running the code in this checkout. Two
    silent divergences have already come out of that gap.

    Reachable and current are kept apart on purpose. A deployment that does not
    answer needs a different fix from one answering with last month's code, and
    a panel that renders both as a red light will get the wrong one tried first.
    """
    local = local_code_version()
    try:
        config = load_appsscript_config(config_path)
    except SheetError as exc:
        return [{"name": "config", "configured": False, "reachable": False,
                 "version": None, "local": local, "current": False,
                 "error": str(exc), "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}]

    # One deployment. There were two until the legacy spreadsheet was retired,
    # and the second was permanently red because nothing needed it enough to
    # redeploy -- which is how a health panel teaches you to ignore it.
    version, error = _probe(config["cms_url"], timeout=timeout)
    return [{
        "name": "cms",
        "configured": True,
        "reachable": error is None,
        "version": version,
        "local": local,
        # Unknown is not current. A deployment with no version stamp at all is
        # running code from before the stamp existed.
        "current": bool(local) and version == local,
        "error": error,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }]


def table_config(config_path: str = APPSSCRIPT_CONFIG) -> dict:
    """Where the CMS tables are written.

    There used to be a choice here: their own spreadsheet, or -- with
    `--same-sheet` -- alongside the legacy tabs that published newsletters
    read. With the legacy spreadsheet retired there is one destination, so
    there is nothing left to choose and no way to pick the wrong one.
    """
    config = load_appsscript_config(config_path)
    return {"url": config["cms_url"], "token": config["cms_token"],
            "separate": True}


def push_tables(season: dict, config_path: str = APPSSCRIPT_CONFIG,
                dry_run: bool = False, only: Optional[Sequence[str]] = None,
                timeout: float = 120.0,
                allow_correction: bool = False) -> List[dict]:
    """Write every CMS table, one call per table.

    One call each rather than one big call: a table is the unit the Apps Script
    guards (allowlist, header, past-season protection), and a partial failure
    should leave the tables that did land rather than roll everything back into
    an unknown state.
    """
    from . import cms

    tables = cms.tables(season)
    wanted = list(only) if only else TABLE_TABS
    unknown = [name for name in wanted if name not in tables]
    if unknown:
        raise SheetError("no such table: {}".format(", ".join(unknown)))

    results = []
    checked = False
    if dry_run:
        config = None
    else:
        config = table_config(config_path)
    for name in wanted:
        table = tables[name]
        matrix = table.matrix()
        payload = {
            "op": "writeTable",
            "tab": name,
            "year": season["year"],
            "columns": matrix[0],
            "rows": matrix[1:],
        }
        if allow_correction:
            # Only ever set by an explicit flag. A frozen table refuses a
            # changed row without it, which is the point.
            payload["allowCorrection"] = True
        if dry_run:
            results.append({"dry_run": True, "tab": name,
                            "rows": len(table.rows),
                            "columns": len(table.columns)})
            continue
        payload["token"] = config["token"]
        if not checked:
            assert_deployment_current(config["url"])
            checked = True
        try:
            results.append(_call_appsscript(config["url"], payload,
                                            timeout=timeout))
        except SheetError as exc:
            # Keep going. A refused write writes nothing, so the cost of
            # continuing is zero and the benefit is that one run reports every
            # table that needs attention rather than the first one.
            results.append({"tab": name, "error": str(exc), "total": 0})
    return results


def tables_to_csv(season: dict, out_dir: str) -> List[str]:
    """Write each table as a CSV, for inspecting before anything is deployed."""
    from . import cms

    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    written = []
    for name, table in cms.tables(season).items():
        path = os.path.join(out_dir, "{}.csv".format(name))
        with open(path, "w", newline="") as fh:
            writer = csv.writer(fh)
            for row in table.matrix():
                writer.writerow(row)
        written.append(path)
    return sorted(written)
