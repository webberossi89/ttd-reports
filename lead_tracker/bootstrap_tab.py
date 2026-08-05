"""One-time tab scaffolder for a Shapeshift Lead Tracker sheet.

Creates (or replaces, with --force) a client tab laid out as:

  A1: <display_name> — 2026 Lead Tracker
  A3: Month   B3: January  C3: February ... M3: December   N3: YTD
  A4: Total Leads
  A5: SEO - Organic
  A6: SEO - GBP
  A7: PPC
  A8: Direct
  A9: Referral

YTD column = SUM(B:M) on each row. Row labels match config.yaml `rows:` keys
so write_sheet.py finds them automatically.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import yaml
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SHEETS_CREDS = pathlib.Path.home() / "recnation/lsa-refresh/.secrets/sheets.yaml"

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

ROW_LABELS = [
    "Total Leads",
    "SEO - Organic",
    "SEO - GBP",
    "PPC",
    "Direct",
    "Referral",
]


def load_sheets_service():
    cfg = yaml.safe_load(SHEETS_CREDS.read_text())
    creds = Credentials(
        token=None,
        refresh_token=cfg["refresh_token"],
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=cfg["scopes"],
    )
    creds.refresh(Request())
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def get_or_create_tab(svc, sid: str, tab: str, force: bool) -> int:
    meta = svc.spreadsheets().get(spreadsheetId=sid, fields="sheets.properties").execute()
    by_title = {s["properties"]["title"]: s["properties"] for s in meta["sheets"]}
    if tab in by_title:
        if not force:
            return by_title[tab]["sheetId"]
        # Wipe contents
        sid_int = by_title[tab]["sheetId"]
        svc.spreadsheets().values().clear(spreadsheetId=sid, range=f"'{tab}'!A1:Z1000").execute()
        return sid_int
    # Otherwise rename Sheet1 if present, else add new
    if "Sheet1" in by_title and not force:
        old_id = by_title["Sheet1"]["sheetId"]
        svc.spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={"requests": [{"updateSheetProperties": {"properties": {"sheetId": old_id, "title": tab}, "fields": "title"}}]},
        ).execute()
        return old_id
    resp = svc.spreadsheets().batchUpdate(
        spreadsheetId=sid,
        body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
    ).execute()
    return resp["replies"][0]["addSheet"]["properties"]["sheetId"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--force", action="store_true", help="Wipe existing tab content before writing layout")
    args = ap.parse_args()

    config = yaml.safe_load(pathlib.Path(args.config).expanduser().read_text())
    sid = config["spreadsheet_id"]
    tab = config["tab_name"]
    title = config["display_name"]

    svc = load_sheets_service()
    sheet_id = get_or_create_tab(svc, sid, tab, args.force)
    print(f"Using tab {tab!r} (sheetId={sheet_id})", file=sys.stderr)

    # Build the layout
    header_row = [f"{title}: 2026 Lead Tracker"]
    anchor_row = ["Month", *MONTHS, "YTD"]
    body_rows: list[list] = []
    for label in ROW_LABELS:
        # cols B..M are 12 month inputs, N = YTD formula. Leave inputs blank.
        body_rows.append([label, *[""] * 12, f"=SUM(B{len(body_rows)+4}:M{len(body_rows)+4})"])

    values = [header_row, [], anchor_row, *body_rows]
    svc.spreadsheets().values().update(
        spreadsheetId=sid,
        range=f"'{tab}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()

    # Formatting: bold header + anchor, freeze first 3 rows + col A
    requests = [
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 3, "frozenColumnCount": 1}},
                "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
            }
        },
        # Header bold + size 14
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 14},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 14}}},
                "fields": "userEnteredFormat.textFormat",
            }
        },
        # Anchor row bold
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 2, "endRowIndex": 3, "startColumnIndex": 0, "endColumnIndex": 14},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.93, "green": 0.93, "blue": 0.93}}},
                "fields": "userEnteredFormat.textFormat,userEnteredFormat.backgroundColor",
            }
        },
        # Total Leads row bold
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 3, "endRowIndex": 4, "startColumnIndex": 0, "endColumnIndex": 14},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat",
            }
        },
        # Col A bold
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 3, "endRowIndex": 3 + len(ROW_LABELS), "startColumnIndex": 0, "endColumnIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat",
            }
        },
        # Center numbers in B..N
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 2, "endRowIndex": 3 + len(ROW_LABELS), "startColumnIndex": 1, "endColumnIndex": 14},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat.horizontalAlignment",
            }
        },
        # Col A width
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 160},
                "fields": "pixelSize",
            }
        },
        # Cols B..N width
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 14},
                "properties": {"pixelSize": 80},
                "fields": "pixelSize",
            }
        },
    ]
    svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": requests}).execute()
    print(f"Layout written: 1 header + 12 months + YTD, {len(ROW_LABELS)} channel rows.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
