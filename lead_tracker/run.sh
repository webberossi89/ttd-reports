#!/usr/bin/env bash
# Shapeshift Lead Tracker refresh runner.
#
# Usage:
#   run.sh <client>                  # previous calendar month (close-out, protected)
#   run.sh <client> 2026-04          # specific month (protected)
#   run.sh <client> --current-month  # MTD refresh of current month (force-overwrite)
set -euo pipefail

UV_BIN="$(command -v uv || true)"
[[ -z "$UV_BIN" && -x "$HOME/.local/bin/uv" ]] && UV_BIN="$HOME/.local/bin/uv"
if [[ -z "$UV_BIN" ]]; then
  echo "ERROR: uv not found" >&2
  exit 1
fi

if prev_month="$(date -d 'last month' +%Y-%m 2>/dev/null)"; then :
elif prev_month="$(date -v-1m +%Y-%m 2>/dev/null)"; then :
else echo "ERROR: no GNU/BSD date" >&2; exit 1
fi
current_month="$(date +%Y-%m)"

CLIENT="${1:-}"
MTD=0
if [[ "${2:-}" == "--current-month" ]]; then
  TARGET_MONTH="$current_month"; MTD=1
elif [[ -n "${2:-}" ]]; then
  TARGET_MONTH="$2"
else
  TARGET_MONTH="$prev_month"
fi

if [[ -z "$CLIENT" ]]; then
  echo "Usage: $0 <client> [YYYY-MM | --current-month]" >&2
  echo "Clients:" >&2
  ls "$HOME/shapeshift-reports/clients" 2>/dev/null | sed 's/^/  /' >&2
  exit 1
fi

CONFIG="$HOME/shapeshift-reports/clients/$CLIENT/config.yaml"
LOG_DIR="$HOME/shapeshift-reports/clients/$CLIENT/logs"
ENGINE="$HOME/shapeshift-reports/lead_tracker"

[[ ! -f "$CONFIG" ]] && { echo "ERROR: missing $CONFIG" >&2; exit 1; }
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/run-$(date +%Y%m%d-%H%M%S).log"

PROTECT_FLAG="--protect-manual"
[[ "$MTD" == "1" ]] && PROTECT_FLAG=""

{
  if [[ "$MTD" == "1" ]]; then
    echo "==== Shapeshift Lead Tracker MTD: $CLIENT month=$TARGET_MONTH (force) ===="
  else
    echo "==== Shapeshift Lead Tracker: $CLIENT month=$TARGET_MONTH (protected) ===="
  fi
  echo "Started $(date)"
  cd "$HOME/mcp/servers/google-ads"
  "$UV_BIN" run python3 "$ENGINE/write_sheet.py" --config "$CONFIG" --months "$TARGET_MONTH" $PROTECT_FLAG
  echo "==== Done $(date) ===="
} >>"$LOG" 2>&1

tail -1 "$LOG"
