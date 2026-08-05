"""Pull WhatConverts leads for a Shapeshift client, bucket by channel, and
return per-month counts.

Channels (default):
  - seo_organic   : Organic SERP traffic (Google/Bing/etc.), NOT GBP
  - seo_gbp       : Google Business Profile listing (calls + website clicks)
  - ppc           : Any paid media (Google Ads, Bing Ads, Meta, etc.)
  - direct        : Direct/branded/no-referrer
  - referral      : Other inbound (third-party websites, email, social organic)

Each client config supplies WhatConverts profile_id + can override the
channel classification rules. The engine NEVER mutates leads; it groups
read-only.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import yaml
import urllib.parse
import urllib.request
import urllib.error

WC_BASE = "https://app.whatconverts.com/api/v1"

CHANNELS = ("seo_organic", "seo_gbp", "lsa", "ppc", "direct", "referral", "unclassified")


def month_bounds(month: str) -> tuple[str, str]:
    """Return (start, end) inclusive YYYY-MM-DD for the given YYYY-MM."""
    y, m = (int(x) for x in month.split("-"))
    start = date(y, m, 1)
    end = date(y + 1, 1, 1) - timedelta(days=1) if m == 12 else date(y, m + 1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def load_creds(config: dict) -> tuple[str, str]:
    """Read WC api_token + api_secret from the path in config (yaml or env)."""
    creds_path = pathlib.Path(config["wc_creds"]).expanduser()
    if creds_path.suffix in (".yaml", ".yml"):
        c = yaml.safe_load(creds_path.read_text())
    else:
        c = {}
        for line in creds_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            c[k.strip()] = v.strip().strip('"').strip("'")
    token = c.get("api_token") or c.get("WC_API_TOKEN")
    secret = c.get("api_secret") or c.get("WC_API_SECRET")
    if not token or not secret:
        raise RuntimeError(f"Missing api_token/api_secret in {creds_path}")
    return token, secret


def wc_get(path: str, params: dict, token: str, secret: str) -> dict:
    qs = urllib.parse.urlencode(params)
    url = f"{WC_BASE}{path}?{qs}"
    auth = base64.b64encode(f"{token}:{secret}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            body = e.read().decode(errors="replace")[:500]
            raise RuntimeError(f"WC API {e.code} on {url}: {body}") from e
    raise RuntimeError(f"WC API exhausted retries: {url}")


def fetch_leads(profile_id: int, start: str, end: str, token: str, secret: str) -> list[dict]:
    """Pull all leads in [start, end] for a profile via paginated /leads."""
    out: list[dict] = []
    page = 1
    while True:
        data = wc_get(
            "/leads",
            {
                "profile_id": profile_id,
                "start_date": start,
                "end_date": end,
                "page_number": page,
                "leads_per_page": 250,
            },
            token,
            secret,
        )
        rows = data.get("leads") or data.get("data") or []
        out.extend(rows)
        total_pages = (
            data.get("total_pages")
            or data.get("pagination", {}).get("total_pages")
            or 1
        )
        if page >= total_pages or not rows:
            break
        page += 1
    return out


def _lc(s: Any) -> str:
    return str(s or "").strip().lower()


def classify(lead: dict, rules: dict) -> str:
    """Return one of CHANNELS. Rules are applied in order: gbp, lsa, ppc, seo_organic, direct, referral.

    lsa is checked BEFORE ppc so that Local Services Ads leads (identified via
    lead_campaign) peel off cleanly instead of falling into the generic paid
    bucket. lsa stays empty by default, so a client only splits LSA out when
    its config defines an lsa rule; all other clients are unaffected.

    Each rule is a list of "match" dicts. A lead matches a rule if ALL of
    the rule's dict items match. The rule passes if ANY match dict passes.
    Field values are compared case-insensitively as substrings.
    """
    def field(name: str) -> str:
        return _lc(lead.get(name))

    def matches(spec: list[dict]) -> bool:
        if not spec:
            return False
        for clause in spec:
            ok = True
            for k, v in clause.items():
                if isinstance(v, list):
                    needles = [_lc(x) for x in v]
                    if not any(n in field(k) for n in needles):
                        ok = False
                        break
                else:
                    if _lc(v) not in field(k):
                        ok = False
                        break
            if ok:
                return True
        return False

    if matches(rules.get("seo_gbp", [])):
        return "seo_gbp"
    if matches(rules.get("lsa", [])):
        return "lsa"
    if matches(rules.get("ppc", [])):
        return "ppc"
    if matches(rules.get("seo_organic", [])):
        return "seo_organic"
    if matches(rules.get("direct", [])):
        return "direct"
    if matches(rules.get("referral", [])):
        return "referral"
    return "unclassified"


def default_rules() -> dict:
    """Sensible defaults. Override per-client via config.classification_rules."""
    return {
        "seo_gbp": [
            {"lead_source": "google business"},
            {"lead_source": "google my business"},
            {"lead_source": "gmb"},
            {"lead_medium": "profile"},
            {"lead_medium": "gmb"},
            {"referrer": "google.com/maps"},
            {"referrer": "google.com/local"},
            {"utm_source": "gbp"},
            {"utm_medium": "gmb"},
        ],
        "ppc": [
            {"lead_medium": ["cpc", "ppc", "paid"]},
            {"lead_source": ["adwords", "google ads", "bing ads", "meta ads", "facebook ads"]},
            {"gclid": "gclid"},  # any non-empty gclid string contains 'gclid'? falsey-guard below
        ],
        "seo_organic": [
            {"lead_medium": "organic"},
            {"lead_source": ["google", "bing", "yahoo", "duckduckgo"]},
        ],
        "direct": [
            {"lead_medium": "direct"},
            {"lead_source": "direct"},
        ],
        "referral": [
            {"lead_medium": ["referral", "email", "social"]},
        ],
    }


def empty_counts() -> dict:
    return {c: 0 for c in CHANNELS} | {"total": 0}


def bucket_by_month(leads: list[dict], months: list[str], rules: dict, date_field: str,
                    unique_only: bool = True) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {m: empty_counts() for m in months}
    target = set(months)
    skipped_date = 0
    skipped_repeat = 0
    for lead in leads:
        raw = lead.get(date_field) or lead.get("date_created") or lead.get("date")
        ds = str(raw or "")[:10]
        if not ds or len(ds) < 7:
            skipped_date += 1
            continue
        m = ds[:7]
        if m not in target:
            continue
        # WhatConverts' own Unique/Repeat determination (lead_status). Count
        # Unique only by default so repeat callers/submitters aren't tallied.
        if unique_only and _lc(lead.get("lead_status")) == "repeat":
            skipped_repeat += 1
            continue
        ch = classify(lead, rules)
        out[m][ch] += 1
        out[m]["total"] += 1
    if skipped_date:
        print(f"  (skipped {skipped_date} leads with unparseable date)", file=sys.stderr)
    if unique_only and skipped_repeat:
        print(f"  (excluded {skipped_repeat} WhatConverts 'Repeat' leads; counting Unique only)", file=sys.stderr)
    return out


def pull(config: dict, months: list[str]) -> dict[str, dict[str, int]]:
    token, secret = load_creds(config)
    rules = default_rules()
    overrides = config.get("classification_rules") or {}
    for k, v in overrides.items():
        rules[k] = v  # full override per channel
    profile_id = int(config["wc_profile_id"])
    date_field = config.get("wc_date_field", "date_created")

    start, _ = month_bounds(months[0])
    _, end = month_bounds(months[-1])
    unique_only = config.get("unique_only", True)

    print(f"Fetching WC leads profile={profile_id} {start}..{end}...", file=sys.stderr)
    leads = fetch_leads(profile_id, start, end, token, secret)
    print(f"  {len(leads)} leads returned", file=sys.stderr)
    return bucket_by_month(leads, months, rules, date_field, unique_only)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--months", nargs="+", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sample", type=int, default=0, help="Print N raw lead rows for inspection (then exit)")
    args = ap.parse_args()

    config = yaml.safe_load(pathlib.Path(args.config).expanduser().read_text())

    if args.sample:
        token, secret = load_creds(config)
        start, _ = month_bounds(args.months[0])
        _, end = month_bounds(args.months[-1])
        leads = fetch_leads(int(config["wc_profile_id"]), start, end, token, secret)
        for r in leads[: args.sample]:
            print(json.dumps(r, indent=2, default=str))
        print(f"\nTotal leads in range: {len(leads)}", file=sys.stderr)
        return 0

    results = pull(config, args.months)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        cols = [*CHANNELS, "total"]
        print(f"\n{'Month':<10} " + " ".join(f"{c:>14}" for c in cols))
        for m in args.months:
            r = results[m]
            print(f"{m:<10} " + " ".join(f"{r[c]:>14}" for c in cols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
