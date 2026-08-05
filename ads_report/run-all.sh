#!/usr/bin/env bash
# Build the Google Ads + LSA "Monthly Report" sheet for every Shapeshift
# client that has an ads_report.yaml under ~/shapeshift-reports/clients/.
#
# build_report.py always refreshes Jan..current month from the live Google
# Ads + WhatConverts sources, so the SAME command serves both triggers:
#   - weekly (Mondays): current-month MTD gets refreshed
#   - monthly (3rd):    the now-complete previous month is written final
#
# Invoked by Windows Task Scheduler via:
#   wsl.exe bash -lc "~/shapeshift-reports/ads_report/run-all.sh"
#
# Optional arg: --month YYYY-MM to (re)write a single month for all clients.
set -uo pipefail

CLIENTS_DIR="$HOME/shapeshift-reports/clients"
ENGINE="$HOME/shapeshift-reports/ads_report/build_report.py"
# Python with the Google Ads SDK + Sheets client (the MCP server venv).
PY="$HOME/mcp/servers/google-ads/.venv/bin/python"
LOG_DIR="$HOME/shapeshift-reports/logs"
mkdir -p "$LOG_DIR"

EXTRA_ARGS=()
if [[ "${1:-}" == "--month" && -n "${2:-}" ]]; then
  EXTRA_ARGS=(--month "$2")
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/ads-report-$STAMP.log"

{
  echo "==================================================================="
  echo "Shapeshift Ads Report batch run"
  echo "Args:    ${EXTRA_ARGS[*]:-<full refresh Jan..current>}"
  echo "Started: $(date)"
  echo "Host:    $(hostname)"
  echo "==================================================================="
} | tee "$LOG"

declare -a OK=() FAILED=()
shopt -s nullglob
for cfg in "$CLIENTS_DIR"/*/ads_report.yaml; do
  client="$(basename "$(dirname "$cfg")")"
  [[ "$client" == _* ]] && continue
  echo "" | tee -a "$LOG"
  echo "--- $client ---" | tee -a "$LOG"
  if "$PY" "$ENGINE" --config "$cfg" "${EXTRA_ARGS[@]}" >>"$LOG" 2>&1; then
    OK+=("$client"); echo "  OK" | tee -a "$LOG"
  else
    FAILED+=("$client"); echo "  FAILED (see $LOG)" | tee -a "$LOG"
  fi
done

{
  echo ""
  echo "Summary: ${#OK[@]} ok / ${#FAILED[@]} failed"
  [[ ${#OK[@]}     -gt 0 ]] && echo "  OK:     ${OK[*]}"
  [[ ${#FAILED[@]} -gt 0 ]] && echo "  FAILED: ${FAILED[*]}"
  echo "Finished: $(date)"
  echo "Log: $LOG"
} | tee -a "$LOG"

[[ ${#FAILED[@]} -eq 0 ]] || exit 1
