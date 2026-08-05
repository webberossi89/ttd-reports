"""Write Shapeshift client's monthly lead counts (by channel) to a Google Sheet.

Layout assumed (one tab per client/year):
  Col A row N: row label ("SEO - Organic", "SEO - GBP", "PPC", "Direct",
               "Referral", "Total" etc.)
  Anchor row (e.g. row containing "Month" header): month names in cols B..M.

Config supplies:
  spreadsheet_id, tab_name, anchor_text (default "Month"),
  rows: {row_label: channel_key} mapping.

protect-manual mode preserves any non-zero cell already in the tab so
manual overrides (e.g. flagged spam recounts) stick.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pull_wc import pull, CHANNELS  # noqa: E402

SHEETS_CREDS = pathlib.Path.home() / "recnation/lsa-refresh/.secrets/sheets.yaml"

MONTH_NAMES = {
    "01": "January", "02": "February", "03": "March",
    "04": "April", "05": "May", "06": "June",
    "07": "July", "08": "August", "09": "September",
    "10": "October", "11": "November", "12": "December",
}


def col_index_to_letter(idx: int) -> str:
    s, n = "", idx
    while True:
        s = chr(ord("A") + n % 26) + s
        n = n // 26 - 1
        if n < 0:
            return s


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


def find_anchor_row(svc, sid: str, tab: str, anchor_text: str) -> int:
    """Return 1-indexed row in col A or row 1 whose first cell == anchor_text."""
    resp = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=f"'{tab}'!A1:Z50"
    ).execute()
    rows = resp.get("values", [])
    for i, r in enumerate(rows, start=1):
        if r and str(r[0]).strip().lower() == anchor_text.strip().lower():
            return i
    raise RuntimeError(f"Anchor {anchor_text!r} not found in cols A-Z rows 1-50 of {tab!r}")


def find_month_columns(svc, sid: str, tab: str, anchor_row: int) -> dict[str, str]:
    resp = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=f"'{tab}'!{anchor_row}:{anchor_row}"
    ).execute()
    rows = resp.get("values", [])
    if not rows:
        return {}
    out = {}
    for i, v in enumerate(rows[0]):
        name = str(v or "").strip()
        if name in MONTH_NAMES.values():
            out[name] = col_index_to_letter(i)
    return out


def find_label_rows(svc, sid: str, tab: str, labels: list[str]) -> dict[str, int]:
    """Find each row label in col A, return 1-indexed row numbers."""
    resp = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=f"'{tab}'!A1:A300"
    ).execute()
    rows = resp.get("values", [])
    lookup = {l.strip().lower(): l for l in labels}
    out: dict[str, int] = {}
    for i, r in enumerate(rows, start=1):
        if not r:
            continue
        key = str(r[0] or "").strip().lower()
        if key in lookup:
            out[lookup[key]] = i
    missing = set(labels) - set(out)
    if missing:
        raise RuntimeError(f"Could not find row labels in col A: {sorted(missing)}")
    return out


def build_updates(
    config: dict,
    results: dict[str, dict[str, int]],
    label_rows: dict[str, int],
    month_cols: dict[str, str],
    months: list[str],
    tab: str,
) -> list[dict]:
    updates: list[dict] = []
    for label, channel in config["rows"].items():
        if channel not in CHANNELS and channel != "total":
            raise RuntimeError(f"Unknown channel key {channel!r} for row {label!r}")
        row = label_rows[label]
        for m in months:
            month_name = MONTH_NAMES[m.split("-")[1]]
            if month_name not in month_cols:
                continue
            val = results.get(m, {}).get(channel)
            if val is None:
                continue
            updates.append(
                {"range": f"'{tab}'!{month_cols[month_name]}{row}", "values": [[int(val)]]}
            )
    return updates


def _provenance_path(config_path: str) -> pathlib.Path:
    """Sidecar storing the last value this engine auto-wrote per cell range."""
    return pathlib.Path(config_path).expanduser().parent / ".last_write.json"


def load_provenance(config_path: str) -> dict[str, str]:
    p = _provenance_path(config_path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return {}


def save_provenance(config_path: str, written: dict[str, str]) -> None:
    p = _provenance_path(config_path)
    prior = load_provenance(config_path)
    prior.update(written)
    try:
        p.write_text(json.dumps(prior, indent=2, sort_keys=True))
    except OSError as e:
        print(f"  WARN: could not save provenance to {p}: {e}", file=sys.stderr)


def _as_number(cell) -> float | None:
    if isinstance(cell, (int, float)):
        return float(cell)
    if isinstance(cell, str):
        try:
            return float(cell.replace("$", "").replace(",", ""))
        except ValueError:
            return None
    return None


def filter_protected(
    svc, sid: str, updates: list[dict], prior: dict[str, str]
) -> tuple[list[dict], list[dict]]:
    """Keep updates whose target cell is safe to overwrite.

    A cell is writable when it is empty, zero, OR its current value matches the
    last value this engine auto-wrote there (i.e. no human has touched it since).
    Only cells a human manually changed away from the last auto-write are skipped.
    This lets month-end finals replace a stale mid-month MTD snapshot while still
    preserving genuine manual overrides.
    """
    if not updates:
        return [], []
    ranges = [u["range"] for u in updates]
    resp = svc.spreadsheets().values().batchGet(
        spreadsheetId=sid, ranges=ranges, valueRenderOption="UNFORMATTED_VALUE"
    ).execute()
    keep, skip = [], []
    for u, vr in zip(updates, resp.get("valueRanges", [])):
        existing = vr.get("values")
        cell = existing[0][0] if existing and existing[0] else None
        is_writable = cell in (None, "")
        cell_num = _as_number(cell)
        if not is_writable and cell_num is not None:
            is_writable = cell_num == 0
        # Unchanged since our last auto-write -> safe to refresh with finals.
        if not is_writable and u["range"] in prior:
            prior_num = _as_number(prior[u["range"]])
            if prior_num is not None and cell_num is not None and prior_num == cell_num:
                is_writable = True
        (keep if is_writable else skip).append({**u, **({"existing": cell} if not is_writable else {})})
    return keep, skip


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--months", nargs="+", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--protect-manual", action="store_true")
    args = ap.parse_args()

    config = yaml.safe_load(pathlib.Path(args.config).expanduser().read_text())

    print(f"[1/4] Pulling {config['display_name']} for {args.months}...", file=sys.stderr)
    results = pull(config, args.months)
    for m in args.months:
        print(f"  {m}: {results[m]}", file=sys.stderr)

    svc = load_sheets_service()
    sid = config["spreadsheet_id"]
    tab = config["tab_name"]

    print("[2/4] Locating anchor + label rows...", file=sys.stderr)
    anchor_text = config.get("anchor_text", "Month")
    anchor_row = find_anchor_row(svc, sid, tab, anchor_text)
    month_cols = find_month_columns(svc, sid, tab, anchor_row)
    label_rows = find_label_rows(svc, sid, tab, list(config["rows"].keys()))
    print(f"  anchor row={anchor_row} cols={month_cols}", file=sys.stderr)
    print(f"  label rows={label_rows}", file=sys.stderr)

    print("[3/4] Building updates...", file=sys.stderr)
    updates = build_updates(config, results, label_rows, month_cols, args.months, tab)
    print(f"  {len(updates)} cell updates queued", file=sys.stderr)

    if args.protect_manual and updates:
        prior = load_provenance(args.config)
        updates, skipped = filter_protected(svc, sid, updates, prior)
        print(f"  protect-manual: keeping {len(updates)}, skipping {len(skipped)}", file=sys.stderr)
        for s in skipped:
            print(f"    SKIP {s['range']:<24} existing={s.get('existing')!r} (manual edit)", file=sys.stderr)

    if args.dry_run:
        print("\nDRY RUN. Would write:", file=sys.stderr)
        for u in updates:
            print(f"  {u['range']:<24} -> {u['values'][0][0]}")
        return 0

    if not updates:
        print("  nothing to write", file=sys.stderr)
        return 0

    print("[4/4] Writing to sheet...", file=sys.stderr)
    body = {"valueInputOption": "USER_ENTERED", "data": updates}
    resp = svc.spreadsheets().values().batchUpdate(spreadsheetId=sid, body=body).execute()
    print(f"  wrote cells={resp.get('totalUpdatedCells')}", file=sys.stderr)
    # Record what we wrote so a later close-out can tell stale auto-writes from
    # genuine manual edits.
    save_provenance(args.config, {u["range"]: str(u["values"][0][0]) for u in updates})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
