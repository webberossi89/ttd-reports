#!/usr/bin/env bash
# Sync WhatConverts leads into the Shapeshift client lead sheets (replaces Zapier Zaps).
#
# Runs EVERY config_*.yaml in this directory, so adding a client is just dropping
# in a new config_<client>.yaml. Invoked by Windows Task Scheduler every ~15 min via:
#   wsl.exe bash -lc "~/shapeshift-reports/lead_sheet_sync/run.sh"
#
# Idempotent: each sync dedups by Lead ID, so extra runs never double-write.
set -uo pipefail

DIR="$HOME/shapeshift-reports/lead_sheet_sync"
ENGINE="$DIR/sync_leads.py"
# Python venv carrying the Google Sheets client (shared with the ads report engine).
PY="$HOME/mcp/servers/google-ads/.venv/bin/python"
LOG_DIR="$HOME/shapeshift-reports/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/lead-sheet-sync.log"

# Push YouForm submissions into WhatConverts FIRST, so a form submission can
# become a WC lead and reach the client's sheet in the same 15-minute cycle.
# (Replaces the Zapier "YouForm -> WhatConverts" Zaps.)
YF_RUN="$HOME/shapeshift-reports/youform_wc_sync/run.sh"
[ -x "$YF_RUN" ] && "$YF_RUN"

shopt -s nullglob
{
  echo "=== Shapeshift lead-sheet sync: $(date) ==="
  for cfg in "$DIR"/config_*.yaml; do
    echo "--- $(basename "$cfg") ---"
    "$PY" "$ENGINE" --config "$cfg"
  done
  echo ""
} >>"$LOG" 2>&1
