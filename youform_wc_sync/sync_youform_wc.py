"""Push YouForm submissions into WhatConverts as web-form leads.

Replaces the Zapier "YouForm -> WhatConverts" Zap, which is being sunset.

Why this exists at all: WhatConverts' page script cannot see inside the
YouForm iframe, so its native web-form capture never fires for these forms
(it matches forms by Aria-Label on in-page markup). The only way a YouForm
submission becomes a WhatConverts lead is an out-of-band push like this one.

What the retired Zap did wrong: it forwarded only email + phone. Every lead
landed in WhatConverts with a blank Contact Name, blank Message and blank
form name, which is why the client's lead sheet has empty columns. This
script forwards the full submission:

    name      -> contact_name
    email     -> email_address
    phone     -> phone_number
    textarea  -> additional_fields["Message"]
    anything else answered -> additional_fields[<question text>]
    form name -> form_name

Attribution note: YouForm captures NO gclid/utm/landing-url on these forms
(``hidden_fields`` declares utm_medium/utm_campaign but nothing populates
them). So lead_source/lead_medium are deliberately NOT sent -- WhatConverts
will record these as direct/none, exactly as it does today. We do not invent
attribution we cannot observe. Fixing that requires capturing gclid into a
YouForm hidden field on the live landing pages; see the project memory.

Dedup is three-layered, because the WhatConverts API has NO delete endpoint
and a duplicate lead is therefore permanent:
  1. a local state file mapping YouForm submission id -> WC lead id
  2. a ``cutover_at`` floor so historical submissions are never backfilled
  3. a live pre-flight check against WhatConverts (email + timestamp match),
     which catches the case where the state file is lost or restored stale

Usage:
    python sync_youform_wc.py --config config_south_coast_demo.yaml [--dry-run]
    python sync_youform_wc.py --config ... --seed   # record state, push nothing
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import yaml

WC_BASE = "https://app.whatconverts.com/api/v1"
YF_BASE = "https://app.youform.com/api"

# YouForm's API rejects python-urllib's default User-Agent with a 403, so all
# YouForm calls shell out to curl. Verified 2026-06-23 and again 2026-07-31.
CURL_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
def _read_env_file(path: pathlib.Path) -> dict:
    """Parse a KEY=value .env file (also accepts YAML)."""
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text()) or {}
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_wc_creds(cfg: dict) -> tuple[str, str]:
    c = _read_env_file(pathlib.Path(cfg["wc_creds"]).expanduser())
    token = c.get("api_token") or c.get("WC_API_TOKEN")
    secret = c.get("api_secret") or c.get("WC_API_SECRET")
    if not token or not secret:
        raise RuntimeError(f"Missing WhatConverts api_token/api_secret in {cfg['wc_creds']}")
    return token, secret


def load_yf_key(cfg: dict) -> str:
    c = _read_env_file(pathlib.Path(cfg["youform_creds"]).expanduser())
    key = c.get("YOUFORM_API_KEY") or c.get("api_key")
    if not key:
        raise RuntimeError(f"Missing YOUFORM_API_KEY in {cfg['youform_creds']}")
    return key


# --------------------------------------------------------------------------- #
# YouForm
# --------------------------------------------------------------------------- #
def yf_get(path: str, key: str) -> dict:
    url = f"{YF_BASE}{path}"
    for attempt in range(4):
        proc = subprocess.run(
            ["curl", "-sS", "--max-time", "45", "-H", f"Authorization: Bearer {key}",
             "-H", "Accept: application/json", "-A", CURL_UA, url],
            capture_output=True, text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                pass
        if attempt < 3:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"YouForm GET failed: {url} :: {proc.stdout[:300]}{proc.stderr[:300]}")


def yf_forms(key: str) -> dict:
    """All forms on the account, keyed by slug (carries the fields.blocks map)."""
    d = yf_get("/forms?per_page=100", key)
    forms = d.get("data", d)
    if isinstance(forms, dict):
        forms = forms.get("data", [])
    return {f.get("slug"): f for f in forms if f.get("slug")}


def yf_submissions(slug: str, key: str, max_pages: int = 20) -> list[dict]:
    """Submissions for one form, newest first."""
    out, page = [], 1
    while page <= max_pages:
        d = yf_get(f"/forms/{slug}/submissions?per_page=100&page={page}", key)["data"]
        out += d.get("data", [])
        if not d.get("next_page_url"):
            break
        page += 1
    out.sort(key=lambda s: str(s.get("created_at") or ""), reverse=True)
    return out


# --------------------------------------------------------------------------- #
# Field resolution
# --------------------------------------------------------------------------- #
_TEMPLATE_VAR = re.compile(r"\{[0-9a-f-]{8,}\}")
_TAGS = re.compile(r"<[^>]+>")


def clean_label(text: str, limit: int = 60) -> str:
    """Turn a YouForm question into a short, human field label."""
    s = _TAGS.sub("", str(text or ""))
    s = _TEMPLATE_VAR.sub("", s).replace("  ", " ").strip(" ,.:;?")
    s = " ".join(s.split())
    return (s[: limit - 1] + "…") if len(s) > limit else s


def classify_blocks(form: dict) -> dict:
    """Map a form's answerable blocks to roles.

    Returns {"email": id, "phone": id, "name": id, "message": id,
             "labels": {block_id: label}}.
    Roles are detected from the block definition rather than hardcoded UUIDs,
    so the sync survives the client editing or re-duplicating the form.
    """
    blocks = ((form.get("fields") or {}).get("blocks")) or []
    roles = {"email": None, "phone": None, "name": None, "message": None, "labels": {}}
    for b in blocks:
        btype = str(b.get("type") or "")
        if btype in ("text", "statement", "thankyou"):
            continue  # display-only blocks carry no answer
        bid, q = b.get("id"), str(b.get("question") or "")
        if not bid:
            continue
        roles["labels"][bid] = clean_label(q) or b.get("display_name") or "Field"
        if btype == "phone" and not roles["phone"]:
            roles["phone"] = bid
        elif b.get("is_email") and not roles["email"]:
            roles["email"] = bid
        elif btype == "textarea" and not roles["message"]:
            roles["message"] = bid
        elif btype == "input" and not roles["name"] and re.search(r"\bname\b", q, re.I):
            roles["name"] = bid
    return roles


# YouForm returns hidden-field values in the submission's ``data`` map keyed by
# the hidden field NAME (e.g. "gclid"), not by a block UUID. Route those to the
# matching WhatConverts create-lead parameter instead of letting them fall
# through to additional_fields as an unlabelled "Field".
ATTRIBUTION_TO_WC = {
    "gclid": "gclid",
    "msclkid": "msclkid",
    "fbclid": "fbclid",
    "utm_source": "lead_source",
    "utm_medium": "lead_medium",
    "utm_campaign": "lead_campaign",
    "utm_term": "lead_keyword",
    "utm_content": "lead_content",
}
# Google's iOS/privacy click ids. WhatConverts has no documented parameter for
# these, so keep them as labelled additional fields rather than dropping them.
ATTRIBUTION_KEEP_AS_FIELD = ("gbraid", "wbraid")


def answer_text(val) -> str:
    """Flatten a YouForm answer value (str | {id,value} | list) to text."""
    if val is None:
        return ""
    if isinstance(val, dict):
        return str(val.get("value") or "").strip()
    if isinstance(val, list):
        return ", ".join(p for p in (answer_text(v) for v in val) if p)
    return str(val).strip()


def build_lead(sub: dict, form: dict, roles: dict, cfg: dict) -> dict:
    """Map a YouForm submission to WhatConverts create-lead parameters."""
    data = sub.get("data") or {}
    ts = str(sub.get("completed_at") or sub.get("created_at") or "")
    # '2026-07-28T18:29:56.000000Z' -> '2026-07-28T18:29:56Z'
    date_created = re.sub(r"\.\d+Z$", "Z", ts)

    lead = {
        "profile_id": int(cfg["wc_profile_id"]),
        "lead_type": "web_form",
        "send_notification": bool(cfg.get("send_notification", False)),
        "date_created": date_created,
        "form_name": str(form.get("name") or "").strip(),
    }
    submitted_name = answer_text(data.get(roles["name"])) if roles["name"] else ""
    if submitted_name:
        lead["contact_name"] = submitted_name
    if roles["email"]:
        v = answer_text(data.get(roles["email"]))
        if v:
            lead["email_address"] = v
    if roles["phone"]:
        v = answer_text(data.get(roles["phone"]))
        if v:
            lead["phone_number"] = v

    # Everything else answered becomes an additional field, so the message and
    # any service-selection question reach the lead sheet instead of vanishing.
    extra: dict[str, str] = {}
    # The name goes in here TOO, not just contact_name. WhatConverts silently
    # discards contact_name on a Web Form lead (verified 2026-07-31 on lead
    # 250017591, via both create and edit): it fills that column only from a
    # per-form field mapping configured in the WC UI. The lead-sheet sync's
    # name_from_fields() reads additional_fields, so writing "Name" here is
    # what actually populates the client's Contact Name column.
    if submitted_name:
        extra["Name"] = submitted_name
    for bid, raw in data.items():
        if bid in (roles["name"], roles["email"], roles["phone"]):
            continue
        v = answer_text(raw)
        if not v:
            continue
        key = str(bid).strip().lower()
        if key in ATTRIBUTION_TO_WC:
            lead[ATTRIBUTION_TO_WC[key]] = v
            continue
        if key in ATTRIBUTION_KEEP_AS_FIELD:
            extra[key] = v
            continue
        label = "Message" if bid == roles["message"] else roles["labels"].get(bid, "Field")
        extra[label] = v
    if extra:
        lead["_additional_fields"] = extra
    return lead


# --------------------------------------------------------------------------- #
# WhatConverts
# --------------------------------------------------------------------------- #
def wc_request(method: str, path: str, token: str, secret: str,
               params: dict | None = None, body: bytes | None = None,
               content_type: str | None = None) -> dict:
    url = f"{WC_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    auth = base64.b64encode(f"{token}:{secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(
                f"WC API {e.code} on {method} {url}: {e.read().decode(errors='replace')[:500]}"
            ) from e
    raise RuntimeError(f"WC API unreachable: {url}")


def wc_recent_leads(profile_id: int, start: str, end: str, token: str, secret: str) -> list[dict]:
    out, page = [], 1
    while page <= 20:
        d = wc_request("GET", "/leads", token, secret, params={
            "profile_id": profile_id, "start_date": start, "end_date": end,
            "leads_per_page": 250, "page_number": page,
        })
        out += d.get("leads", [])
        if page >= int(d.get("total_pages") or 1):
            break
        page += 1
    return out


def wc_create_lead(lead: dict, token: str, secret: str) -> dict:
    """POST a lead. additional_fields uses the documented bracket notation."""
    payload = {k: v for k, v in lead.items() if k != "_additional_fields"}
    form = {k: ("true" if v is True else "false" if v is False else str(v))
            for k, v in payload.items()}
    for label, value in (lead.get("_additional_fields") or {}).items():
        form[f"additional_fields[{label}]"] = value
    body = urllib.parse.urlencode(form).encode()
    return wc_request("POST", "/leads", token, secret, body=body,
                      content_type="application/x-www-form-urlencoded")


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def load_state(path: pathlib.Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"  WARNING: state file {path} unreadable; treating as empty", file=sys.stderr)
    return {}


def save_state(path: pathlib.Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    tmp.replace(path)  # atomic, so a crash mid-write cannot corrupt state


def norm_email(s) -> str:
    return str(s or "").strip().lower()


def parse_iso(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(re.sub(r"\.\d+Z$", "Z", str(s)).replace("Z", "+00:00"))
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true", help="Show what would be pushed, push nothing")
    ap.add_argument("--seed", action="store_true",
                    help="Record existing submissions as already-synced without pushing")
    ap.add_argument("--limit", type=int, default=0,
                    help="Create at most N leads this run (0 = no limit). Used to verify "
                         "the first live push before releasing the rest, since WhatConverts "
                         "has no delete endpoint.")
    args = ap.parse_args()

    cfg = yaml.safe_load(pathlib.Path(args.config).expanduser().read_text())
    yf_key = load_yf_key(cfg)
    token, secret = load_wc_creds(cfg)
    profile_id = int(cfg["wc_profile_id"])
    state_path = pathlib.Path(cfg["state_file"]).expanduser()
    state = load_state(state_path)
    cutover = parse_iso(cfg["cutover_at"])
    if cutover is None:
        raise RuntimeError(f"Invalid cutover_at: {cfg.get('cutover_at')!r}")
    match_window = int(cfg.get("duplicate_match_minutes", 30))

    now = datetime.now(timezone.utc)
    forms = yf_forms(yf_key)

    # Pre-flight: what WhatConverts already holds, so we never double-create.
    # The window must reach back to cutover_at, not just lookback_days -- any
    # eligible submission older than the queried window would otherwise look
    # new and get re-created, and WhatConverts has no delete endpoint.
    lookback = int(cfg.get("lookback_days", 7))
    wc_start = min(cutover, now - timedelta(days=lookback + 1))
    existing = wc_recent_leads(
        profile_id,
        wc_start.date().isoformat(),
        (now + timedelta(days=1)).date().isoformat(),
        token, secret,
    )
    existing_index: list[tuple[str, datetime | None]] = [
        (norm_email(l.get("contact_email_address") or l.get("email_address")),
         parse_iso(l.get("date_created")))
        for l in existing
    ]
    print(f"WhatConverts: {len(existing)} leads since {wc_start.date().isoformat()}", file=sys.stderr)

    total_pushed = total_skipped = total_dupe = 0

    for entry in cfg["forms"]:
        slug = entry["slug"] if isinstance(entry, dict) else str(entry)
        form = forms.get(slug)
        if not form:
            print(f"  ERROR: form {slug} not found on the YouForm account; skipping", file=sys.stderr)
            continue
        roles = classify_blocks(form)
        subs = yf_submissions(slug, yf_key)
        form_state = state.setdefault(slug, {})
        print(f"\n--- {slug} ({form.get('name')!r}) : {len(subs)} submissions ---", file=sys.stderr)

        for sub in subs:
            if args.limit and total_pushed >= args.limit:
                print(f"  --limit {args.limit} reached; stopping", file=sys.stderr)
                break
            sid = str(sub.get("id"))
            created = parse_iso(sub.get("completed_at") or sub.get("created_at"))
            if created is None or created < cutover:
                continue                                  # before cutover: never backfill
            if sid in form_state:
                continue                                  # already synced
            if not sub.get("is_complete"):
                total_skipped += 1
                continue                                  # abandoned mid-form
            if sub.get("is_test"):
                total_skipped += 1
                continue

            lead = build_lead(sub, form, roles, cfg)
            if not lead.get("email_address") and not lead.get("phone_number"):
                total_skipped += 1
                print(f"  skip {sid}: no email or phone", file=sys.stderr)
                continue

            if args.seed:
                form_state[sid] = "seeded"
                continue

            # Guard: does WhatConverts already have this lead (Zap overlap, or
            # a lost state file)? Match on email within a time window.
            em = norm_email(lead.get("email_address"))
            dupe = next(
                (True for e, d in existing_index
                 if em and e == em and d and abs((d - created).total_seconds()) <= match_window * 60),
                False,
            )
            if dupe:
                form_state[sid] = "pre-existing"
                total_dupe += 1
                print(f"  dupe {sid} ({em}) already in WhatConverts; recorded, not re-created",
                      file=sys.stderr)
                continue

            desc = (f"  {sid} | {created:%Y-%m-%d %H:%M} | {lead.get('contact_name','') or '(no name)'} "
                    f"| {lead.get('email_address','')} | {lead.get('phone_number','')}")
            if args.dry_run:
                print(desc, file=sys.stderr)
                for k, v in (lead.get("_additional_fields") or {}).items():
                    print(f"        {k}: {v[:100]}", file=sys.stderr)
                total_pushed += 1
                continue

            try:
                resp = wc_create_lead(lead, token, secret)
                new_id = resp.get("lead_id") or (resp.get("leads") or [{}])[0].get("lead_id")
                form_state[sid] = new_id
                total_pushed += 1
                print(f"{desc}  -> WC lead {new_id}", file=sys.stderr)
                save_state(state_path, state)  # persist per lead: a crash cannot duplicate
            except Exception as e:
                print(f"  FAILED {sid}: {type(e).__name__}: {e}", file=sys.stderr)

    if not args.dry_run:
        save_state(state_path, state)

    verb = "would push" if args.dry_run else ("seeded" if args.seed else "pushed")
    print(f"\n{verb}: {total_pushed} | skipped: {total_skipped} | already in WC: {total_dupe}",
          file=sys.stderr)
    if args.dry_run:
        print("(dry run — nothing written to WhatConverts)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
