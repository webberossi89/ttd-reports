"""Build a per-client "Monthly Report" tab from Google Ads + WhatConverts.

Fills the raw-input rows of a Shapeshift "<Client> Monthly Report" workbook:
  - clicks / impressions / cost  : Google Ads (per advertising_channel_type)
  - form_leads / phone_leads     : WhatConverts lead_type within a WC channel
  - LSA leads / cost             : WhatConverts lsa bucket + Google Ads cost

Formula rows (CTR, CPC, CPL, Total, Conversion Rate) and manual rows
(Qualified Leads, Microsoft Ads, PMax when unused) are never touched.

Month columns are B..M (Jan..Dec); column index == month number.

Sources of truth (per client decision):
  - Lead COUNTS come from WhatConverts lead_type (clean Web Form vs Phone Call
    split, no conversion-action double counting).
  - SPEND / clicks / impressions come from Google Ads.

Usage:
  build_report.py --config clients/mr-cheapee/ads_report.yaml
  build_report.py --config ... --month 2026-05      # single month
  build_report.py --config ... --dry-run            # print, don't write
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys
from collections import defaultdict

import yaml
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build as build_sheets

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "lead_tracker"))
from pull_wc import load_creds, fetch_leads, classify, default_rules  # noqa: E402

SHEETS_CREDS = pathlib.Path.home() / "recnation/lsa-refresh/.secrets/sheets.yaml"


def col_letter(month_num: int) -> str:
    """Month 1 (Jan) -> 'B', ... month 12 (Dec) -> 'M'."""
    return chr(ord("A") + month_num)


def months_for(year: int, single: str | None) -> list[str]:
    if single:
        return [single]
    today = dt.date.today()
    last = 12 if year < today.year else today.month
    return [f"{year}-{m:02d}" for m in range(1, last + 1)]


# --------------------------------------------------------------------------- #
# Google Ads
# --------------------------------------------------------------------------- #
def pull_google_ads(cfg: dict, year: int) -> dict[str, dict[str, dict[str, float]]]:
    """Return {channel: {month: {clicks, impressions, cost}}}."""
    from google.ads.googleads.client import GoogleAdsClient

    ga = cfg["google_ads"]
    client = GoogleAdsClient.load_from_storage(str(pathlib.Path(ga["creds"]).expanduser()))
    svc = client.get_service("GoogleAdsService")
    customer_id = str(ga["customer_id"])

    query = f"""
        SELECT segments.month,
               campaign.advertising_channel_type,
               metrics.clicks,
               metrics.impressions,
               metrics.cost_micros
        FROM campaign
        WHERE segments.date BETWEEN '{year}-01-01' AND '{year}-12-31'
    """
    out: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"clicks": 0, "impressions": 0, "cost": 0.0})
    )
    stream = svc.search_stream(customer_id=customer_id, query=query)
    for batch in stream:
        for row in batch.results:
            channel = row.campaign.advertising_channel_type.name
            month = str(row.segments.month)[:7]  # YYYY-MM
            agg = out[channel][month]
            agg["clicks"] += row.metrics.clicks
            agg["impressions"] += row.metrics.impressions
            agg["cost"] += row.metrics.cost_micros / 1_000_000
    return out


# --------------------------------------------------------------------------- #
# WhatConverts
# --------------------------------------------------------------------------- #
def pull_wc_leadtype(cfg: dict, months: list[str]) -> dict[str, dict[str, dict[str, int]]]:
    """Return {wc_channel: {month: {form, phone, total}}}.

    Counts UNIQUE leads only, using WhatConverts' own determination: the
    lead_status field is "Unique" or "Repeat". We keep "Unique" and drop
    "Repeat" (set unique_only: false in config to count all).
    """
    token, secret = load_creds(cfg)
    rules = default_rules()
    for k, v in (cfg.get("classification_rules") or {}).items():
        rules[k] = v
    profile_id = int(cfg["wc_profile_id"])
    date_field = cfg.get("wc_date_field", "date_created")

    y0, m0 = months[0].split("-")
    y1, m1 = months[-1].split("-")
    start = f"{y0}-{m0}-01"
    last_day = (dt.date(int(y1), int(m1) % 12 + 1, 1) - dt.timedelta(days=1)) if int(m1) != 12 else dt.date(int(y1), 12, 31)
    end = last_day.isoformat()

    print(f"Fetching WC leads profile={profile_id} {start}..{end}...", file=sys.stderr)
    leads = fetch_leads(profile_id, start, end, token, secret)
    print(f"  {len(leads)} leads returned", file=sys.stderr)

    out: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"form": 0, "phone": 0, "total": 0, "qualified": 0})
    )
    target = set(months)
    unique_only = cfg.get("unique_only", True)
    # Optional: peel paid-social (Meta/Facebook) leads out of the generic ppc
    # bucket by lead_source, so they are never counted as Google Ads Search
    # leads. The WC `ppc` rule matches lead_medium=cpc, which Meta also uses,
    # so without this a client running Meta has its Google CPL understated.
    # Empty by default; only clients that set social_source_match are affected.
    social_match = [s.lower() for s in (cfg.get("social_source_match") or [])]
    # Optional: peel PMax leads out of the generic ppc bucket by lead_campaign,
    # so a Performance Max report section can be filled separately from Search.
    pmax_match = [p.lower() for p in (cfg.get("pmax_campaign_match") or [])]
    n_repeat = 0
    for L in leads:
        ds = str(L.get(date_field) or L.get("date_created") or "")[:7]
        if ds not in target:
            continue
        if unique_only and str(L.get("lead_status") or "").strip().lower() == "repeat":
            n_repeat += 1
            continue  # WhatConverts flagged this as a repeat lead
        ch = classify(L, rules)
        if ch == "ppc" and social_match:
            ls = str(L.get("lead_source") or "").lower()
            if any(s in ls for s in social_match):
                ch = "ppc_social"
        if ch == "ppc" and pmax_match:
            lc = str(L.get("lead_campaign") or "").lower()
            if any(p in lc for p in pmax_match):
                ch = "ppc_pmax"
        lt = str(L.get("lead_type") or "").strip().lower()
        type_key = "form" if "form" in lt else ("phone" if ("phone" in lt or "call" in lt) else None)
        if type_key is None:
            continue
        bucket = out[ch][ds]
        bucket[type_key] += 1
        bucket["total"] += 1
        # Qualified = a unique lead the team marked quotable=Yes (real opportunity).
        if str(L.get("quotable") or "").strip().lower() == "yes":
            bucket["qualified"] += 1
    if unique_only and n_repeat:
        print(f"  (excluded {n_repeat} WhatConverts 'Repeat' leads; counting Unique only)", file=sys.stderr)
    return out


# --------------------------------------------------------------------------- #
# Sheets
# --------------------------------------------------------------------------- #
def sheets_service():
    c = yaml.safe_load(SHEETS_CREDS.read_text())
    creds = Credentials(
        token=None, refresh_token=c["refresh_token"], client_id=c["client_id"],
        client_secret=c["client_secret"], token_uri="https://oauth2.googleapis.com/token",
        scopes=c["scopes"],
    )
    creds.refresh(Request())
    return build_sheets("sheets", "v4", credentials=creds, cache_discovery=False)


def build_updates(cfg: dict, months: list[str], ga: dict, wc: dict) -> list[dict]:
    """Map sources to (range, value) cell updates for the configured sections."""
    tab = cfg["tab_name"]
    updates: list[dict] = []

    def put(row: int, month: str, value):
        col = col_letter(int(month.split("-")[1]))
        updates.append({"range": f"'{tab}'!{col}{row}", "values": [[value]]})

    for name, sec in cfg["sections"].items():
        rows = sec["rows"]
        gch = sec.get("google_ads_channel")
        wch = sec.get("wc_channel")
        # Optional column-A labels for any rows this engine introduces.
        for row, label in (sec.get("row_labels") or {}).items():
            updates.append({"range": f"'{tab}'!A{row}", "values": [[label]]})
        for m in months:
            g = ga.get(gch, {}).get(m, {}) if gch else {}
            w = wc.get(wch, {}).get(m, {}) if wch else {}
            if "clicks" in rows:
                put(rows["clicks"], m, int(g.get("clicks", 0)))
            if "impressions" in rows:
                put(rows["impressions"], m, int(g.get("impressions", 0)))
            if "cost" in rows:
                put(rows["cost"], m, round(g.get("cost", 0.0), 2))
            if "form_leads" in rows:
                put(rows["form_leads"], m, int(w.get("form", 0)))
            if "phone_leads" in rows:
                put(rows["phone_leads"], m, int(w.get("phone", 0)))
            if "leads" in rows:  # LSA single leads row (WC total)
                put(rows["leads"], m, int(w.get("total", 0)))
            if "qualified_leads" in rows:
                # May sum qualified across several WC channels (e.g. Total Paid
                # Search qualified = ppc + ppc_pmax).
                qchs = sec.get("qualified_wc_channels", [wch])
                qv = sum(int(wc.get(c, {}).get(m, {}).get("qualified", 0)) for c in qchs)
                put(rows["qualified_leads"], m, qv)
    return updates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--month", help="single YYYY-MM (default: Jan..current)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(pathlib.Path(args.config).expanduser().read_text())
    year = int(cfg.get("year", dt.date.today().year))
    months = months_for(year, args.month)

    ga = pull_google_ads(cfg, year)
    wc = pull_wc_leadtype(cfg, months)
    updates = build_updates(cfg, months, ga, wc)

    # Console summary
    print(f"\n{cfg['display_name']} -> {cfg['spreadsheet_id']} tab {cfg['tab_name']!r}")
    print(f"Months: {months[0]}..{months[-1]}")
    for name, sec in cfg["sections"].items():
        gch, wch = sec.get("google_ads_channel"), sec.get("wc_channel")
        print(f"\n[{name}]  (Google Ads {gch} + WC {wch})")
        hdr = f"{'Month':<9}{'Clicks':>8}{'Impr':>8}{'Cost':>11}{'Form':>7}{'Phone':>7}{'Leads':>7}{'Qual':>6}"
        print(hdr)
        for m in months:
            g = ga.get(gch, {}).get(m, {})
            w = wc.get(wch, {}).get(m, {})
            print(f"{m:<9}{int(g.get('clicks',0)):>8}{int(g.get('impressions',0)):>8}"
                  f"{g.get('cost',0.0):>11.2f}{w.get('form',0):>7}{w.get('phone',0):>7}{w.get('total',0):>7}{w.get('qualified',0):>6}")

    if args.dry_run:
        print(f"\n[dry-run] {len(updates)} cells would be written.")
        return 0

    svc = sheets_service()
    svc.spreadsheets().values().batchUpdate(
        spreadsheetId=cfg["spreadsheet_id"],
        body={"valueInputOption": "USER_ENTERED", "data": updates},
    ).execute()
    print(f"\nWrote {len(updates)} cells.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
