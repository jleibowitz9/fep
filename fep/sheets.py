"""
Push weekly competitor percentages to the Google Sheet that Framer reads.

THE CONTRACT (agreed with Jacob, enforced below)
------------------------------------------------
The Sheet is a single-purpose pipe to the website. This module writes ONE thing:
the weekly competitor percentages.

    * Writes B2:M20 and nothing else, ever.
    * NEVER writes column A. That holds the week labels.
    * NEVER writes column N or anything right of it. Those hold Jacob's
      placement formulas (first, second, third...) which are computed FROM the
      percentages. Overwriting them would break the live site.
    * Values are matched to competitors BY NAME, read off row 1. If the header
      does not match the roster, the push aborts rather than writing twelve
      columns of misaligned numbers into formulas that feed a public page.

Nineteen data rows: row 2 is week 0, row 20 is week 18. The bye week gets a row
like any other, because the picks do not change but the ESPN weights do, so the
board genuinely moves.

AUTHENTICATION
--------------
An Apps Script web app that lives inside the spreadsheet itself
(`appsscript/Code.gs`). No Google Cloud project, no service account, no key
file.

That is not just simpler, it is necessary: service account key creation is
blocked on Jacob's account by the `iam.disableServiceAccountKeyCreation`
organization policy. An Apps Script deployment runs as him and is not subject
to it.

The deployment URL and a shared token live in `credentials/appsscript.json`,
which is gitignored. The URL alone is enough to reach the script, so the token
is a second factor, and the script itself refuses to write anywhere except
B2:M20 of a tab whose header matches the roster.

Service accounts are still supported (`push(..., transport="service_account")`)
in case the policy is ever lifted, but Apps Script is the default.

If neither is configured, everything still works: use `as_rows` / `to_csv` /
`to_tsv_block` and paste. That path needs no setup at all.
"""

from __future__ import annotations

import csv
import io
import os
import re
from typing import Dict, List, Optional, Sequence

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

CREDENTIALS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "credentials")
DEFAULT_KEY_PATH = os.path.join(CREDENTIALS_DIR, "service-account.json")

# The only shape this module is allowed to write.
ALLOWED_FIRST_COLUMN = "B"
ALLOWED_LAST_COLUMN = "M"

_RANGE_RE = re.compile(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$")


class SheetError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# the guard
# ---------------------------------------------------------------------------

def _column_number(letters: str) -> int:
    value = 0
    for char in letters:
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value


def assert_safe_range(a1: str) -> dict:
    """Refuse anything that could touch column A or the formula columns.

    This is the load-bearing safety check in this module. It runs before every
    write, including the dry-run path, so a bad range can never reach the API.
    """
    match = _RANGE_RE.match(a1.strip().upper())
    if not match:
        raise SheetError(
            "range {!r} is not a simple A1 rectangle like B2:M20".format(a1)
        )
    first_col, first_row, last_col, last_row = match.groups()

    if _column_number(first_col) < _column_number(ALLOWED_FIRST_COLUMN):
        raise SheetError(
            "range {} starts at column {} which would overwrite column A "
            "(the week labels). Refusing.".format(a1, first_col)
        )
    if _column_number(last_col) > _column_number(ALLOWED_LAST_COLUMN):
        raise SheetError(
            "range {} extends to column {} which would overwrite Jacob's "
            "placement formulas in column N onward. Refusing.".format(a1, last_col)
        )
    if int(first_row) < 2:
        raise SheetError(
            "range {} includes row 1, which is the header. Refusing.".format(a1)
        )
    return {
        "first_col": first_col, "last_col": last_col,
        "first_row": int(first_row), "last_row": int(last_row),
        "width": _column_number(last_col) - _column_number(first_col) + 1,
        "height": int(last_row) - int(first_row) + 1,
    }


# ---------------------------------------------------------------------------
# building the block
# ---------------------------------------------------------------------------

def as_rows(season: dict, roster: Optional[Sequence[str]] = None) -> List[List[object]]:
    """The B2:M20 block: one row per week, one column per competitor.

    Weeks with no snapshot yet come out as empty strings, which leaves those
    cells blank rather than writing a misleading zero (0.0 means eliminated).
    """
    sheet = season.get("sheet", {})
    first_week = sheet.get("first_week", 0)
    last_week = sheet.get("last_week", 18)
    roster = list(roster or season["roster"])

    snapshots = {s["week"]: s["weighted"] for s in season.get("snapshots", [])}
    rows = []
    for week in range(first_week, last_week + 1):
        board = snapshots.get(week)
        if board is None:
            rows.append(["" for _ in roster])
        else:
            rows.append([board.get(name, "") for name in roster])
    return rows


def to_csv(season: dict, roster: Optional[Sequence[str]] = None,
           include_header: bool = True) -> str:
    """CSV of the same block, for the no-auth copy-paste path."""
    roster = list(roster or season["roster"])
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if include_header:
        writer.writerow(["week"] + roster)
    sheet = season.get("sheet", {})
    first_week = sheet.get("first_week", 0)
    for offset, row in enumerate(as_rows(season, roster)):
        writer.writerow([first_week + offset] + list(row))
    return buffer.getvalue()


def to_tsv_block(season: dict, roster: Optional[Sequence[str]] = None) -> str:
    """Tab-separated values with no week column, ready to paste straight into B2.

    Tabs are what Sheets expects on paste, so this lands correctly in the grid
    without an import step.
    """
    return "\n".join(
        "\t".join("" if cell == "" else str(cell) for cell in row)
        for row in as_rows(season, roster)
    )


# ---------------------------------------------------------------------------
# the API path
# ---------------------------------------------------------------------------

def credentials_available(key_path: str = DEFAULT_KEY_PATH) -> bool:
    return os.path.exists(key_path)


def _service(key_path: str):
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise SheetError(
            "Google client libraries are not installed. "
            "Run: pip install -r requirements.txt  ({})".format(exc)
        )
    if not os.path.exists(key_path):
        raise SheetError(
            "no service-account key at {}. See README.md for the one-time "
            "setup, or use the CSV / paste path instead.".format(key_path)
        )
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def read_header(season: dict, key_path: str = DEFAULT_KEY_PATH) -> List[str]:
    """Row 1 of the target tab, so we can verify column alignment."""
    sheet = season["sheet"]
    service = _service(key_path)
    a1 = "{}!A1:Z1".format(sheet["tab"]) if sheet.get("tab") else "A1:Z1"
    response = service.spreadsheets().values().get(
        spreadsheetId=sheet["spreadsheet_id"], range=a1
    ).execute()
    values = response.get("values") or [[]]
    return [str(cell).strip() for cell in values[0]]


def verify_alignment(season: dict, key_path: str = DEFAULT_KEY_PATH) -> dict:
    """Confirm the Sheet's columns B..M are the roster, in order.

    Returns a report. Raises if it cannot be made safe.
    """
    header = read_header(season, key_path)
    bounds = assert_safe_range(season["sheet"]["range"])
    start = _column_number(bounds["first_col"]) - 1   # 0-based index into header
    end = start + bounds["width"]
    in_sheet = header[start:end]
    roster = list(season["roster"])

    if len(in_sheet) < len(roster):
        raise SheetError(
            "sheet header has {} columns in {}..{} but the roster has {}: {}".format(
                len(in_sheet), bounds["first_col"], bounds["last_col"], len(roster), in_sheet
            )
        )
    if [n.lower() for n in in_sheet] != [n.lower() for n in roster]:
        raise SheetError(
            "sheet header does not match the roster, refusing to write.\n"
            "  sheet : {}\n  roster: {}".format(in_sheet, roster)
        )
    return {"header": in_sheet, "bounds": bounds, "ok": True}


def push_via_service_account(season: dict, key_path: str = DEFAULT_KEY_PATH,
                             tab: Optional[str] = None,
                             dry_run: bool = False) -> dict:
    """Write the weekly percentages. Aborts on any misalignment.

    Pass tab= to target a scratch copy, which is how the first push should
    always be done.
    """
    sheet = dict(season["sheet"])
    if tab:
        sheet["tab"] = tab
    if not sheet.get("spreadsheet_id"):
        raise SheetError("season file has no sheet.spreadsheet_id set")

    bounds = assert_safe_range(sheet["range"])
    rows = as_rows(season)

    if len(rows) != bounds["height"]:
        raise SheetError(
            "built {} rows but range {} covers {}".format(
                len(rows), sheet["range"], bounds["height"]
            )
        )
    for row in rows:
        if len(row) != bounds["width"]:
            raise SheetError(
                "row has {} values but range {} is {} columns wide".format(
                    len(row), sheet["range"], bounds["width"]
                )
            )

    target = "{}!{}".format(sheet["tab"], sheet["range"]) if sheet.get("tab") else sheet["range"]

    if dry_run:
        return {"dry_run": True, "range": target, "rows": len(rows),
                "columns": bounds["width"], "values": rows}

    scoped = dict(season)
    scoped["sheet"] = sheet
    verify_alignment(scoped, key_path)

    service = _service(key_path)
    response = service.spreadsheets().values().update(
        spreadsheetId=sheet["spreadsheet_id"],
        range=target,
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()
    return {
        "dry_run": False,
        "range": target,
        "updated_cells": response.get("updatedCells"),
        "updated_range": response.get("updatedRange"),
    }


def service_account_email(key_path: str = DEFAULT_KEY_PATH) -> Optional[str]:
    """The robot address the Sheet has to be shared with."""
    import json
    if not os.path.exists(key_path):
        return None
    with open(key_path) as fh:
        return json.load(fh).get("client_email")


# ---------------------------------------------------------------------------
# the Apps Script path (the default)
# ---------------------------------------------------------------------------

APPSSCRIPT_CONFIG = os.path.join(CREDENTIALS_DIR, "appsscript.json")


def appsscript_available(config_path: str = APPSSCRIPT_CONFIG) -> bool:
    return os.path.exists(config_path)


def load_appsscript_config(config_path: str = APPSSCRIPT_CONFIG) -> dict:
    import json
    if not os.path.exists(config_path):
        raise SheetError(
            "no Apps Script config at {}. See appsscript/README.md for the "
            "one-time setup, or use the paste path instead.".format(config_path))
    with open(config_path) as fh:
        config = json.load(fh)
    for field in ("url", "token"):
        if not config.get(field):
            raise SheetError("{} is missing {!r}".format(config_path, field))
    if "/exec" not in config["url"]:
        raise SheetError(
            "the Apps Script URL should end in /exec (a deployment), not /dev. "
            "got: {}".format(config["url"]))
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


def push_via_appsscript(season: dict, config_path: str = APPSSCRIPT_CONFIG,
                        tab: Optional[str] = None, dry_run: bool = False) -> dict:
    """Write the weekly percentages through the in-sheet Apps Script."""
    sheet = dict(season["sheet"])
    if tab:
        sheet["tab"] = tab
    if not sheet.get("tab"):
        raise SheetError("season file has no sheet.tab set")

    bounds = assert_safe_range(sheet["range"])
    rows = as_rows(season)
    roster = list(season["roster"])

    if len(rows) != bounds["height"]:
        raise SheetError("built {} rows but range {} covers {}".format(
            len(rows), sheet["range"], bounds["height"]))
    if len(roster) != bounds["width"]:
        raise SheetError("roster has {} names but range {} is {} columns".format(
            len(roster), sheet["range"], bounds["width"]))

    payload = {
        "tab": sheet["tab"],
        "firstRow": bounds["first_row"],
        "roster": roster,
        "values": rows,
    }

    if dry_run:
        return {"dry_run": True, "transport": "appsscript",
                "range": "{}!{}".format(sheet["tab"], sheet["range"]),
                "rows": len(rows), "columns": bounds["width"], "values": rows}

    config = load_appsscript_config(config_path)
    payload["token"] = config["token"]
    result = _call_appsscript(config["url"], payload)
    return {
        "dry_run": False,
        "transport": "appsscript",
        "range": result.get("range"),
        "updated_cells": result.get("wrote"),
        "updated_range": result.get("range"),
    }


def push(season: dict, tab: Optional[str] = None, dry_run: bool = False,
         transport: Optional[str] = None, **kwargs) -> dict:
    """Write the weekly percentages, choosing whatever transport is configured.

    Apps Script is preferred because service account keys are blocked by an
    organization policy on this account.
    """
    if transport is None:
        transport = "appsscript" if (
            appsscript_available() or not credentials_available()
        ) else "service_account"

    if transport == "appsscript":
        return push_via_appsscript(season, tab=tab, dry_run=dry_run, **kwargs)
    if transport == "service_account":
        return push_via_service_account(season, tab=tab, dry_run=dry_run, **kwargs)
    raise SheetError("unknown transport {!r}".format(transport))
