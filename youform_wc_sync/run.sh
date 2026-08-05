#!/usr/bin/env bash
# Push YouForm submissions into WhatConverts (replaces the Zapier Zaps).
#
# Runs EVERY config_*.yaml in this directory, so adding a client is just
# dropping in a new config_<client>.yaml.
#
# Ordering matters: this must run BEFORE lead_sheet_sync/run.sh, so a form
# submission becomes a WhatConverts lead and then reaches the client's lead
# sheet within the same 15-minute cycle. lead_sheet_sync/run.sh invokes this
# script first for exactly that reason.
#
# Idempotent: each sync dedups against a local state file AND against
# WhatConverts itself, so extra runs never double-create a lead. This matters
# more than usual because the WhatConverts API has no delete endpoint.
set -uo pipefail

DIR="$HOME/shapeshift-reports/youform_wc_sync"
ENGINE="$DIR/sync_youform_wc.py"
PY="$HOME/mcp/servers/google-ads/.venv/bin/python"
LOG_DIR="$HOME/shapeshift-reports/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/youform-wc-sync.log"

shopt -s nullglob
{
  echo "=== YouForm -> WhatConverts sync: $(date) ==="
  for cfg in "$DIR"/config_*.yaml; do
    echo "--- $(basename "$cfg") ---"
    "$PY" "$ENGINE" --config "$cfg"
  done
  echo ""
} >>"$LOG" 2>&1
