#!/usr/bin/env bash
# Run the Shapeshift Lead Tracker refresh for every client that has a
# config.yaml under ~/shapeshift-reports/clients/. Designed for Windows
# Task Scheduler to invoke via:
#   wsl.exe bash -lc "~/shapeshift-reports/lead_tracker/run-all.sh"
#
# Usage:
#   run-all.sh                   # previous calendar month (protected)
#   run-all.sh 2026-04           # specific month, protected
#   run-all.sh --month 2026-04
#   run-all.sh --current-month   # current month MTD, force-overwrite
#                                # (weekly trigger)
#
# Exit code: 0 if every client succeeded, non-zero if any failed (does
# NOT stop on first failure; tries every client and reports at end).
set -uo pipefail

CLIENTS_DIR="$HOME/shapeshift-reports/clients"
ENGINE_DIR="$HOME/shapeshift-reports/lead_tracker"
COMBINED_LOG_DIR="$HOME/shapeshift-reports/logs"
mkdir -p "$COMBINED_LOG_DIR"

# Resolve target month + mode.
MTD=0
TARGET_MONTH=""
if [[ "${1:-}" == "--current-month" ]]; then
  MTD=1
  TARGET_MONTH="$(date +%Y-%m)"
elif [[ "${1:-}" == "--month" ]]; then
  TARGET_MONTH="${2:-}"
else
  TARGET_MONTH="${1:-}"
fi
if [[ -z "$TARGET_MONTH" ]]; then
  if ! TARGET_MONTH="$(date -d 'last month' +%Y-%m 2>/dev/null)"; then
    TARGET_MONTH="$(date -v-1m +%Y-%m 2>/dev/null)"
  fi
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
COMBINED_LOG="$COMBINED_LOG_DIR/run-all-$STAMP.log"

MODE_LABEL="protected (monthly close-out)"
RUN_ARG="$TARGET_MONTH"
if [[ "$MTD" == "1" ]]; then
  MODE_LABEL="MTD force-overwrite (weekly refresh)"
  RUN_ARG="--current-month"
fi

{
  echo "==================================================================="
  echo "Shapeshift Lead Tracker batch run"
  echo "Month:   $TARGET_MONTH"
  echo "Mode:    $MODE_LABEL"
  echo "Started: $(date)"
  echo "Host:    $(hostname)"
  echo "==================================================================="
} | tee "$COMBINED_LOG"

declare -a FAILED=()
declare -a OK=()

shopt -s nullglob
for cfg in "$CLIENTS_DIR"/*/config.yaml; do
  client="$(basename "$(dirname "$cfg")")"
  # Skip helper files (e.g. _rules_template.yaml lives at clients/ root)
  [[ "$client" == _* ]] && continue
  echo ""                                       | tee -a "$COMBINED_LOG"
  echo "--- $client ($TARGET_MONTH) ---"        | tee -a "$COMBINED_LOG"
  if "$ENGINE_DIR/run.sh" "$client" "$RUN_ARG" >>"$COMBINED_LOG" 2>&1; then
    OK+=("$client")
    echo "  OK"                                 | tee -a "$COMBINED_LOG"
  else
    FAILED+=("$client")
    echo "  FAILED (see per-client log under $CLIENTS_DIR/$client/logs/)" \
                                                | tee -a "$COMBINED_LOG"
  fi
done

{
  echo ""
  echo "==================================================================="
  echo "Summary: ${#OK[@]} ok / ${#FAILED[@]} failed"
  [[ ${#OK[@]}     -gt 0 ]] && echo "  OK:     ${OK[*]}"
  [[ ${#FAILED[@]} -gt 0 ]] && echo "  FAILED: ${FAILED[*]}"
  echo "Finished: $(date)"
  echo "Combined log: $COMBINED_LOG"
  echo "==================================================================="
} | tee -a "$COMBINED_LOG"

[[ ${#FAILED[@]} -eq 0 ]] || exit 1
