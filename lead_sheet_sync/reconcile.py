#!/usr/bin/env python3
"""One-off reconciliation: compare WhatConverts leads vs what's in each sheet.

Pulls all 2026 leads for a client, applies the SAME write-eligibility filters
the sync uses (skip spam, keep repeats per config, hold very-recent calls still
inside the AI-summary wait), then reports which eligible WC lead IDs are NOT in
the destination sheet.
"""
import os
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.expanduser("~/shapeshift-reports/lead_tracker"))
import yaml  # noqa: E402

import sync_leads as s  # noqa: E402
from pull_wc import load_creds, fetch_leads  # noqa: E402

START = "2026-01-01"
END = datetime.now(timezone.utc).date().isoformat()


def reconcile(cfg_path: str):
    cfg = yaml.safe_load(open(cfg_path))
    name = cfg.get("display_name", cfg_path)
    include_repeat = cfg.get("include_repeat", True)
    include_spam = cfg.get("include_spam", False)
    wait_min = float(cfg.get("summary_wait_minutes", 25))
    now = datetime.now(timezone.utc)

    tok, sec = load_creds(cfg)
    leads = fetch_leads(int(cfg["wc_profile_id"]), START, END, tok, sec)

    svc = s.sheets_service(pathlib.Path(os.path.expanduser(cfg["sheets_creds"])))
    have = s.existing_lead_ids(svc, cfg["spreadsheet_id"], cfg["tab_name"])

    eligible = 0
    in_sheet = 0
    missing = []
    pending = 0
    for lead in leads:
        lid = str(lead.get("lead_id") or "").strip()
        if not lid:
            continue
        if not include_spam and lead.get("spam"):
            continue
        if not include_repeat and str(lead.get("lead_status") or "").lower() == "repeat":
            continue

        lead_type = str(lead.get("lead_type") or "").lower()
        is_call = "phone" in lead_type or "call" in lead_type
        if is_call and not s.lead_summary_ready(lead):
            created = lead.get("date_created")
            try:
                cdt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                age_min = (now - cdt).total_seconds() / 60.0
            except Exception:
                age_min = wait_min + 1
            if age_min < wait_min:
                pending += 1
                continue  # legitimately held for AI summary

        eligible += 1
        if lid in have:
            in_sheet += 1
        else:
            missing.append((lid, str(lead.get("date_created"))[:19],
                            str(lead.get("lead_type") or ""),
                            str(lead.get("lead_status") or "")))

    print(f"\n===== {name} =====")
    print(f"  WC leads {START}..{END}: {len(leads)}")
    print(f"  eligible to write (after filters): {eligible}")
    print(f"  present in sheet:                  {in_sheet}")
    print(f"  held for AI summary (recent calls): {pending}")
    print(f"  MISSING from sheet:                {len(missing)}")
    for lid, dt, lt, ls in missing[:50]:
        print(f"     {lid:>10}  {dt:<19}  {lt:<12}  {ls}")
    if len(missing) > 50:
        print(f"     ... and {len(missing) - 50} more")
    return len(missing)


if __name__ == "__main__":
    total = 0
    for cfg in sys.argv[1:]:
        total += reconcile(cfg)
    print(f"\nTOTAL MISSING across configs: {total}")
