#!/usr/bin/env python3
"""Backfill blank Contact Name / Phone Number cells in a client's Lead Sheet.

Why this exists
---------------
WhatConverts only auto-maps a web form's *email* field to the lead's standard
properties. Name and phone stay inside ``additional_fields`` unless the field
mapping is configured per web form in the WhatConverts UI. Mr Cheapee was in
that state, so every web-form row landed in the sheet with a blank Contact Name
and a blank Phone Number even though the visitor had typed both.

sync_leads.py now recovers those values on write (see name_from_fields /
phone_from_fields), but it only ever PREPENDS new leads and never revisits a
row it already wrote. This script repairs the rows that were written before
that fix.

Safety
------
- Dry-run by default; ``--apply`` is required to write.
- Only ever fills a cell that is currently BLANK. Never overwrites a value a
  human or WhatConverts already put there.
- Only touches the Contact Name and Phone Number columns.
- Reads every target cell back after writing and reports any drift.

Usage
-----
    python repair_contact_fields.py --config config_mr_cheapee.yaml
    python repair_contact_fields.py --config config_mr_cheapee.yaml --apply
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from datetime import date, timedelta

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "lead_tracker"))

from sync_leads import (  # noqa: E402
    message_for,
    name_from_fields,
    phone_from_fields,
    sheets_service,
)
from pull_wc import load_creds, fetch_leads  # noqa: E402


def col_letter(idx0: int) -> str:
    """0-based column index -> A1 letter (A..Z, then AA..)."""
    s = ""
    n = idx0
    while True:
        s = chr(ord("A") + n % 26) + s
        n = n // 26 - 1
        if n < 0:
            return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--lookback-days", type=int, default=365)
    ap.add_argument("--apply", action="store_true", help="Write. Omit for a dry run.")
    args = ap.parse_args()

    cfg = yaml.safe_load(pathlib.Path(args.config).read_text())
    columns = cfg["columns"]
    try:
        name_i = columns.index("Contact Name")
        phone_i = columns.index("Phone Number")
    except ValueError:
        print("Config has no 'Contact Name'/'Phone Number' column; nothing to repair.")
        return 0
    # Message is optional and repaired on the same terms as the other two: only
    # ever filled when the sheet cell is blank. Added 2026-08-05 for South Coast,
    # whose retired Zapier pipe forwarded only email + phone, so months of
    # web-form rows carry an address and a number and no idea what the person
    # wanted. Recovering the text into WhatConverts does NOT reach the sheet on
    # its own: sync_leads.py only ever prepends and never revisits a written row.
    msg_i = columns.index("Message") if "Message" in columns else None

    token, secret = load_creds(cfg)
    end_d = date.today()
    start_d = end_d - timedelta(days=args.lookback_days)
    leads = fetch_leads(
        cfg["wc_profile_id"], start_d.isoformat(), end_d.isoformat(), token, secret
    )
    by_id = {str(l.get("lead_id")): l for l in leads}
    print(f"WhatConverts: {len(by_id)} leads over the last {args.lookback_days} days")

    svc = sheets_service(pathlib.Path(cfg["sheets_creds"]).expanduser())
    sid = cfg["spreadsheet_id"]
    tab = cfg["tab_name"]
    end = col_letter(len(columns) - 1)
    rows = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=f"'{tab}'!A2:{end}"
    ).execute().get("values", [])
    print(f"Sheet '{tab}': {len(rows)} data rows")

    updates, skipped_no_lead, filled_name, filled_phone, filled_msg = [], 0, 0, 0, 0
    for offset, row in enumerate(rows):
        sheet_row = offset + 2
        lead_id = str(row[0]).strip() if row and len(row) > 0 else ""
        if not lead_id:
            continue
        cur_name = row[name_i].strip() if len(row) > name_i else ""
        cur_phone = row[phone_i].strip() if len(row) > phone_i else ""
        cur_msg = (row[msg_i].strip() if msg_i is not None and len(row) > msg_i else "")
        if cur_name and cur_phone and (msg_i is None or cur_msg):
            continue
        lead = by_id.get(lead_id)
        if lead is None:
            skipped_no_lead += 1
            continue
        if not cur_name:
            v = name_from_fields(lead)
            if v:
                updates.append((f"'{tab}'!{col_letter(name_i)}{sheet_row}", v, lead_id, "name"))
                filled_name += 1
        if not cur_phone:
            v = phone_from_fields(lead)
            if v:
                updates.append((f"'{tab}'!{col_letter(phone_i)}{sheet_row}", v, lead_id, "phone"))
                filled_phone += 1
        if msg_i is not None and not cur_msg:
            v = message_for(lead)
            if v:
                updates.append((f"'{tab}'!{col_letter(msg_i)}{sheet_row}", v, lead_id, "msg"))
                filled_msg += 1

    print(f"\nWould fill {filled_name} Contact Name + {filled_phone} Phone Number "
          f"+ {filled_msg} Message cells ({len(updates)} cells total)")
    if skipped_no_lead:
        print(f"{skipped_no_lead} sheet rows had no matching lead in the WC window "
              f"(older than --lookback-days); re-run with a longer window to cover them.")
    for rng, val, lead_id, kind in updates[:15]:
        print(f"  {rng:<20} {kind:<5} lead {lead_id} -> {val}")
    if len(updates) > 15:
        print(f"  ... and {len(updates) - 15} more")

    if not updates:
        return 0
    if not args.apply:
        print("\nDRY RUN. Re-run with --apply to write.")
        return 0

    svc.spreadsheets().values().batchUpdate(
        spreadsheetId=sid,
        body={
            "valueInputOption": "RAW",
            "data": [{"range": rng, "values": [[val]]} for rng, val, _, _ in updates],
        },
    ).execute()
    print(f"\nWrote {len(updates)} cells. Reading back to verify...")

    read = svc.spreadsheets().values().batchGet(
        spreadsheetId=sid, ranges=[rng for rng, _, _, _ in updates]
    ).execute().get("valueRanges", [])
    drift = 0
    for (rng, val, lead_id, kind), got in zip(updates, read):
        actual = (got.get("values") or [[""]])[0][0] if got.get("values") else ""
        if str(actual).strip() != str(val).strip():
            drift += 1
            print(f"  DRIFT {rng}: sent {val!r}, sheet has {actual!r}")
    print("Verified: no drift." if not drift else f"Verified: {drift} cells drifted.")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
