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
A Google service account. Free, no billing account needed, and unlike user
OAuth its credentials do not expire every 7 days. See README.md for the setup
steps. Jacob creates the credential; this module only consumes it.

If no credential is present, everything still works: use `as_rows` / `to_csv`
and paste. That path is always available and needs no setup at all.
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


def push(season: dict, key_path: str = DEFAULT_KEY_PATH,
         tab: Optional[str] = None, dry_run: bool = False) -> dict:
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
