"""Sync WhatConverts leads into a Google Sheet, replacing a Zapier Zap.

Polls the WhatConverts API for recent leads, dedups against the Lead IDs
already in column A of the destination sheet, and prepends the new ones at
row 2 (newest on top) in the sheet's fixed 18-column order.

Phone-call leads carry an AI "Lead Summary" that WhatConverts generates a
few minutes after the call ends. We therefore hold a phone lead back until
either the summary is present or the lead is older than summary_wait_minutes,
so the "Message" column is never written blank for a call that just landed.

Idempotent: dedup is by Lead ID, so re-running never double-writes.

Usage:
    python sync_leads.py --config config_mr_cheapee.yaml [--dry-run] [--lookback-days N]
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

import yaml
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build as build_sheets

# Reuse the proven WhatConverts client from the lead_tracker engine.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "lead_tracker"))
from pull_wc import load_creds, fetch_leads  # noqa: E402


# --------------------------------------------------------------------------- #
# Field extraction: WhatConverts lead -> destination row
# --------------------------------------------------------------------------- #
def _fmt_time(raw: str) -> str:
    """'2026-06-18T19:38:17Z' -> '2026-06-18 19:38:17' (match existing rows)."""
    s = str(raw or "")
    return s[:19].replace("T", " ")


def _form_message(lead: dict) -> str:
    """Build a Message for a web-form lead from its submitted fields.

    WhatConverts returns ``additional_fields`` as a dict mapping field name ->
    value (e.g. {"First Name": "Luis", "Message": "Hi"}). Older/other shapes
    seen in the wild: a list of {field_name, field_value} dicts, or a list of
    plain strings. Handle all three defensively so a single odd lead can't crash
    the whole sync run.
    """
    af = lead.get("additional_fields")
    parts = []
    if isinstance(af, dict):
        for name, val in af.items():
            name = str(name or "").strip()
            val = str(val or "").strip().replace("\n", " ")
            if val:
                parts.append(f"{name}: {val}" if name else val)
    elif isinstance(af, list):
        for f in af:
            if isinstance(f, dict):
                name = str(f.get("field_name") or f.get("name") or "").strip()
                val = str(f.get("field_value") or f.get("value") or "").strip()
            else:
                name, val = "", str(f or "").strip()
            val = val.replace("\n", " ")
            if val:
                parts.append(f"{name}: {val}" if name else val)
    return " | ".join(parts)


def _af_dict(lead: dict) -> dict:
    """Normalised {label: value} view of a lead's submitted form fields.

    Only the dict shape carries usable labels; the list shapes handled in
    _form_message are normalised here too so callers get one contract.
    """
    af = lead.get("additional_fields")
    out = {}
    if isinstance(af, dict):
        items = af.items()
    elif isinstance(af, list):
        items = [
            (f.get("field_name") or f.get("name") or "", f.get("field_value") or f.get("value") or "")
            for f in af if isinstance(f, dict)
        ]
    else:
        return out
    for name, val in items:
        key = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
        val = str(val or "").strip()
        if key and val:
            out[key] = val
    return out


# Honeypot / anti-spam fields some form plugins submit as real fields.
_AF_IGNORE = ("ifyouareahuman", "honeypot", "leavethisfieldblank")


def _af_get(af: dict, *needles: str) -> str:
    """First value whose normalised label contains one of ``needles``."""
    for key, val in af.items():
        if any(bad in key for bad in _AF_IGNORE):
            continue
        if any(n in key for n in needles):
            return val
    return ""


def name_from_fields(lead: dict) -> str:
    """Recover a contact name from the submitted form fields.

    WhatConverts only auto-maps a form's email field; name and phone stay in
    ``additional_fields`` unless the field mapping is configured per web form
    in the WC UI. This keeps the sheet populated either way.
    """
    af = _af_dict(lead)
    for exact in ("name", "fullname", "yourname", "contactname"):
        if af.get(exact):
            return af[exact]
    first = _af_get(af, "firstname")
    last = _af_get(af, "lastname")
    if first or last:
        return " ".join(p for p in (first, last) if p)
    # Last resort: any label containing "name" that isn't a company/business name.
    for key, val in af.items():
        if any(bad in key for bad in _AF_IGNORE):
            continue
        if "name" in key and not any(b in key for b in ("company", "business", "username")):
            return val
    return ""


def phone_from_fields(lead: dict) -> str:
    """Recover a phone number from the submitted form fields."""
    val = _af_get(_af_dict(lead), "phone", "mobile", "cell", "telephone")
    # Guard against matching a label like "Phone preference" that holds prose.
    return val if len(re.sub(r"\D", "", val)) >= 7 else ""


def lead_summary_ready(lead: dict) -> bool:
    """True if a phone lead already has its AI Lead Summary populated."""
    analysis = lead.get("lead_analysis") or {}
    if isinstance(analysis, dict):
        return bool(str(analysis.get("Lead Summary") or "").strip())
    return False


def message_for(lead: dict) -> str:
    lead_type = str(lead.get("lead_type") or "")
    if "phone" in lead_type.lower() or "call" in lead_type.lower():
        analysis = lead.get("lead_analysis") or {}
        if isinstance(analysis, dict):
            return str(analysis.get("Lead Summary") or "").strip()
        return ""
    return _form_message(lead)


def notes_value(lead: dict, notes_source: str) -> str:
    """Notes column. Default blank; some clients map it to a WC analysis field."""
    if notes_source == "customer_type":
        analysis = lead.get("lead_analysis") or {}
        if isinstance(analysis, dict):
            return str(analysis.get("Customer Type") or "").strip()
    return ""


def build_row(lead: dict, columns: list[str], notes_source: str = "",
              qualified_from_quotable: bool = False) -> list[str]:
    """Map a WhatConverts lead to a row in the sheet's column order."""
    if qualified_from_quotable:
        q = str(lead.get("quotable") or "").strip().lower()
        qualified_cell = {"yes": "TRUE", "no": "FALSE"}.get(q, "")  # Not Set -> blank
    else:
        qualified_cell = "FALSE"
    values = {
        "Lead ID": str(lead.get("lead_id") or ""),
        "Contact Name": str(
            lead.get("contact_name")
            or lead.get("caller_name")
            or name_from_fields(lead)
            or ""
        ).strip(),
        "Email Address": str(
            lead.get("contact_email_address")
            or _af_get(_af_dict(lead), "email")
            or ""
        ).strip(),
        "Phone Number": str(
            lead.get("phone_number")
            or lead.get("contact_phone_number")
            or lead.get("caller_number")
            or phone_from_fields(lead)
            or ""
        ).strip(),
        "Time": _fmt_time(lead.get("date_created")),
        "Lead Type": str(lead.get("lead_type") or "").strip(),
        "Message": message_for(lead),
        "Qualified Lead?": qualified_cell,
        "Bad Lead": "FALSE",
        "Appointment Booked?": "FALSE",
        # 365 Pools only: client-maintained flag for "quoted a service fee but
        # declined the visit". Always written FALSE; the client edits it.
        "Declined For Service Fee": "FALSE",
        "Deal Closed?": "FALSE",
        "Notes": notes_value(lead, notes_source),
        "Source": str(lead.get("lead_source") or "").strip(),
        "Medium": str(lead.get("lead_medium") or "").strip(),
        "Campaign": str(lead.get("lead_campaign") or "").strip(),
        "Content": str(lead.get("lead_content") or "").strip(),
        "Keyword": str(lead.get("lead_keyword") or "").strip(),
        "GCLID": str(lead.get("gclid") or "").strip(),
        "Referring site": str(lead.get("landing_url") or lead.get("lead_url") or "").strip(),
    }
    return [values.get(c.strip(), "") for c in columns]


# --------------------------------------------------------------------------- #
# Google Sheets
# --------------------------------------------------------------------------- #
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def sheets_service(creds_path: pathlib.Path):
    """Build a Sheets client from either a service-account JSON key or the
    legacy OAuth-user YAML. Detection: a service_account key is JSON with
    `"type": "service_account"`; anything else is treated as the OAuth YAML.
    This lets durable clients (e.g. Ford Piano) auth via a jaredwebber1989
    service account while existing clients keep the goduo OAuth token."""
    raw = creds_path.read_text()
    c = yaml.safe_load(raw)
    if isinstance(c, dict) and c.get("type") == "service_account":
        from google.oauth2 import service_account  # local import; optional dep
        creds = service_account.Credentials.from_service_account_info(
            c, scopes=SHEETS_SCOPES
        )
    else:
        creds = Credentials(
            None,
            refresh_token=c["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=c["client_id"],
            client_secret=c["client_secret"],
            scopes=c["scopes"],
        )
    return build_sheets("sheets", "v4", credentials=creds, cache_discovery=False)


def tab_id(svc, sid: str, tab_name: str) -> int:
    meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
    for sh in meta["sheets"]:
        if sh["properties"]["title"] == tab_name:
            return sh["properties"]["sheetId"]
    raise RuntimeError(f"Tab '{tab_name}' not found in spreadsheet {sid}")


def existing_lead_ids(svc, sid: str, tab_name: str) -> set[str]:
    rng = f"'{tab_name}'!A2:A"
    vals = svc.spreadsheets().values().get(spreadsheetId=sid, range=rng).execute().get("values", [])
    return {str(r[0]).strip() for r in vals if r and str(r[0]).strip()}


def prepend_rows(svc, sid: str, tab_name: str, gid: int, rows: list[list[str]]) -> None:
    """Insert len(rows) blank rows below the header, then write the values."""
    if not rows:
        return
    n = len(rows)
    svc.spreadsheets().batchUpdate(
        spreadsheetId=sid,
        body={
            "requests": [
                {
                    "insertDimension": {
                        "range": {
                            "sheetId": gid,
                            "dimension": "ROWS",
                            "startIndex": 1,   # row 2 (0-based, below header)
                            "endIndex": 1 + n,
                        },
                        "inheritFromBefore": False,
                    }
                }
            ]
        },
    ).execute()
    end_col = chr(ord("A") + len(rows[0]) - 1)
    svc.spreadsheets().values().update(
        spreadsheetId=sid,
        range=f"'{tab_name}'!A2:{end_col}{1 + n}",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true", help="Show what would be written, write nothing")
    ap.add_argument("--lookback-days", type=int, default=None, help="Override config lookback_days")
    args = ap.parse_args()

    cfg = yaml.safe_load(pathlib.Path(args.config).expanduser().read_text())
    columns = [c for c in cfg["columns"]]
    lookback = args.lookback_days if args.lookback_days is not None else int(cfg.get("lookback_days", 3))
    wait_min = int(cfg.get("summary_wait_minutes", 25))
    include_repeat = bool(cfg.get("include_repeat", True))
    include_spam = bool(cfg.get("include_spam", False))
    # Leads to never write, e.g. our own test submissions. Needed because dedup
    # keys on Lead ID read from the sheet, so deleting a row inside the lookback
    # window would otherwise let the next poll re-add it.
    exclude_ids = {str(x).strip() for x in (cfg.get("exclude_lead_ids") or [])}
    notes_source = str(cfg.get("notes_source", "") or "")
    qualified_from_quotable = bool(cfg.get("qualified_from_quotable", False))

    # 1. Pull recent WhatConverts leads.
    token, secret = load_creds(cfg)
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=lookback)).date().isoformat()
    end = now.date().isoformat()
    profile_id = int(cfg["wc_profile_id"])
    print(f"Fetching WC leads profile={profile_id} {start}..{end} ...", file=sys.stderr)
    leads = fetch_leads(profile_id, start, end, token, secret)
    print(f"  {len(leads)} leads returned", file=sys.stderr)

    # 2. Sheet state.
    svc = sheets_service(pathlib.Path(cfg["sheets_creds"]).expanduser())
    sid = cfg["spreadsheet_id"]
    tab = cfg["tab_name"]
    gid = tab_id(svc, sid, tab)
    have = existing_lead_ids(svc, sid, tab)
    print(f"  {len(have)} lead IDs already in sheet", file=sys.stderr)

    # 3. Decide which leads to write.
    to_write: list[dict] = []
    held_for_summary = 0
    for lead in leads:
        lid = str(lead.get("lead_id") or "").strip()
        if not lid or lid in have:
            continue
        if lid in exclude_ids:
            continue
        if not include_spam and lead.get("spam"):
            continue
        if not include_repeat and str(lead.get("lead_status") or "").lower() == "repeat":
            continue

        lead_type = str(lead.get("lead_type") or "").lower()
        is_call = "phone" in lead_type or "call" in lead_type
        if is_call and not lead_summary_ready(lead):
            created = lead.get("date_created")
            try:
                created_dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                age_min = (now - created_dt).total_seconds() / 60.0
            except Exception:
                age_min = wait_min + 1  # unparseable -> don't hold forever
            if age_min < wait_min:
                held_for_summary += 1
                continue  # give the AI summary time; it'll be caught next poll

        to_write.append(lead)

    # Newest first so row 2 ends up as the most recent lead.
    to_write.sort(key=lambda x: str(x.get("date_created") or ""), reverse=True)

    # Build rows per-lead so a single malformed lead is skipped (and logged)
    # instead of aborting the whole batch and blocking every other lead.
    rows = []
    skipped = 0
    for lead in to_write:
        try:
            rows.append(build_row(lead, columns, notes_source, qualified_from_quotable))
        except Exception as e:
            skipped += 1
            print(
                f"  SKIPPED lead {lead.get('lead_id')} ({type(e).__name__}: {e})",
                file=sys.stderr,
            )
    if skipped:
        print(f"  {skipped} lead(s) skipped due to build errors", file=sys.stderr)

    print(f"\nNew leads to write: {len(rows)}"
          + (f"  (holding {held_for_summary} recent calls for AI summary)" if held_for_summary else ""),
          file=sys.stderr)

    if args.dry_run:
        preview = columns.index("Message") if "Message" in columns else 6
        for r in rows[:15]:
            msg = (r[preview][:70] + "...") if len(r[preview]) > 70 else r[preview]
            print(f"  {r[0]:>10} | {r[4]:<19} | {r[5]:<10} | {r[1][:18]:<18} | {msg}")
        if len(rows) > 15:
            print(f"  ... and {len(rows) - 15} more", file=sys.stderr)
        print("\n(dry run — nothing written)", file=sys.stderr)
        return 0

    prepend_rows(svc, sid, tab, gid, rows)
    print(f"Wrote {len(rows)} new leads to '{tab}'.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
