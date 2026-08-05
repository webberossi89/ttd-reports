#!/usr/bin/env bash
# Shapeshift campaign-block report refresh, one client.
#
# Same shape and semantics as the Duo runner (~/duo-reports/lead_tracker/run.sh)
# and it drives the SAME engine; only the clients root differs, so a Shapeshift
# client can never be picked up by a Duo scheduled task and vice versa.
#
# Usage:
#   run.sh <client>                  # previous calendar month (close-out)
#   run.sh <client> 2026-07          # a specific month
#   run.sh <client> --current-month  # current month MTD, force-overwrite
#
# <client> is a directory name under ~/shapeshift-reports/report_clients/
# containing config.yaml (+ campaigns.yaml for the per-campaign shape).
set -euo pipefail

UV_BIN="$(command -v uv || true)"
[[ -z "$UV_BIN" && -x "$HOME/.local/bin/uv" ]] && UV_BIN="$HOME/.local/bin/uv"
if [[ -z "$UV_BIN" ]]; then
  echo "ERROR: uv not found on PATH or in ~/.local/bin/uv" >&2
  exit 1
fi

if prev_month="$(date -d 'last month' +%Y-%m 2>/dev/null)"; then
  :
elif prev_month="$(date -v-1m +%Y-%m 2>/dev/null)"; then
  :
else
  echo "ERROR: neither GNU date -d nor BSD date -v-1m is available" >&2
  exit 1
fi
current_month="$(date +%Y-%m)"

CLIENT="${1:-}"
TARGET_MONTH=""
MTD=0

if [[ "${2:-}" == "--current-month" ]]; then
  TARGET_MONTH="$current_month"
  MTD=1
elif [[ -n "${2:-}" ]]; then
  TARGET_MONTH="$2"
else
  TARGET_MONTH="$prev_month"
fi

if [[ -z "$CLIENT" ]]; then
  echo "Usage: $0 <client> [YYYY-MM | --current-month]" >&2
  echo "Available clients:" >&2
  ls "$HOME/shapeshift-reports/report_clients" 2>/dev/null | sed 's/^/  /' >&2
  exit 1
fi

CONFIG="$HOME/shapeshift-reports/report_clients/$CLIENT/config.yaml"
LOG_DIR="$HOME/shapeshift-reports/report_clients/$CLIENT/logs"
ENGINE="$HOME/duo-reports/lead_tracker"   # shared engine, not a copy

if [[ ! -f "$CONFIG" ]]; then
  echo "ERROR: config not found: $CONFIG" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/run-$(date +%Y%m%d-%H%M%S).log"

# Close-out protects existing values so a hand-entered cell survives. Clients
# with no hand-entered cells (`fully_automated: true`) force-overwrite instead,
# otherwise end-of-month activity landing after the last MTD refresh freezes as
# a stale value the protected close-out would skip forever.
PROTECT_FLAG="--protect-manual"
[[ "$MTD" == "1" ]] && PROTECT_FLAG=""
if [[ "$MTD" == "0" ]] && grep -Eqi '^[[:space:]]*fully_automated:[[:space:]]*(true|yes|1)[[:space:]]*$' "$CONFIG"; then
  PROTECT_FLAG=""
fi

{
  if [[ "$MTD" == "1" ]]; then
    echo "==== Shapeshift report MTD refresh: client=$CLIENT month=$TARGET_MONTH (force-overwrite) ===="
  elif [[ -z "$PROTECT_FLAG" ]]; then
    echo "==== Shapeshift report refresh: client=$CLIENT month=$TARGET_MONTH (close-out, force-overwrite: fully_automated) ===="
  else
    echo "==== Shapeshift report refresh: client=$CLIENT month=$TARGET_MONTH (protected) ===="
  fi
  echo "Started at $(date)"
  cd "$HOME/mcp/servers/google-ads"
  "$UV_BIN" run python3 "$ENGINE/write_sheet.py" \
    --config "$CONFIG" \
    --months "$TARGET_MONTH" \
    $PROTECT_FLAG
  echo "==== Done at $(date) ===="
} >>"$LOG" 2>&1

tail -1 "$LOG"
