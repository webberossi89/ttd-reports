#!/usr/bin/env bash
# Run the campaign-block report for every Shapeshift client that has a
# config.yaml under ~/shapeshift-reports/report_clients/.
#
# Windows Task Scheduler invokes it as:
#   wsl.exe bash -lc "~/shapeshift-reports/campaign_report/run-all.sh"
#
# Usage:
#   run-all.sh                   # previous calendar month (monthly close-out)
#   run-all.sh 2026-07           # a specific month
#   run-all.sh --month 2026-07
#   run-all.sh --current-month   # current month MTD, force-overwrite (daily/weekly)
#
# Exit code: 0 if every client succeeded. It does NOT stop at the first
# failure; every client is attempted and the failures are reported at the end.
set -uo pipefail

CLIENTS_DIR="$HOME/shapeshift-reports/report_clients"
RUNNER="$HOME/shapeshift-reports/campaign_report/run.sh"
COMBINED_LOG_DIR="$HOME/shapeshift-reports/logs"
mkdir -p "$COMBINED_LOG_DIR"

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
COMBINED_LOG="$COMBINED_LOG_DIR/campaign-report-$STAMP.log"

MODE_LABEL="protected (monthly close-out)"
RUN_ARG="$TARGET_MONTH"
if [[ "$MTD" == "1" ]]; then
  MODE_LABEL="MTD force-overwrite"
  RUN_ARG="--current-month"
fi

{
  echo "==================================================================="
  echo "Shapeshift campaign-block report batch run"
  echo "Month:   $TARGET_MONTH"
  echo "Mode:    $MODE_LABEL"
  echo "Started: $(date)"
  echo "Host:    $(hostname)"
  echo "==================================================================="
} | tee "$COMBINED_LOG"

declare -a FAILED=() OK=()
shopt -s nullglob
for cfg in "$CLIENTS_DIR"/*/config.yaml; do
  client="$(basename "$(dirname "$cfg")")"
  [[ "$client" == _* ]] && continue
  echo ""                                | tee -a "$COMBINED_LOG"
  echo "--- $client ($TARGET_MONTH) ---" | tee -a "$COMBINED_LOG"
  if "$RUNNER" "$client" "$RUN_ARG" >>"$COMBINED_LOG" 2>&1; then
    OK+=("$client");     echo "  OK"     | tee -a "$COMBINED_LOG"
  else
    FAILED+=("$client")
    echo "  FAILED (see $CLIENTS_DIR/$client/logs/)" | tee -a "$COMBINED_LOG"
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

# Durable one-line health record, same convention as the Duo runner: a silent
# breakage (renamed tab, revoked credential) is visible at a glance without
# digging through per-run logs.
HEALTH_LOG="$COMBINED_LOG_DIR/campaign-report-health.log"
if [[ ${#FAILED[@]} -eq 0 ]]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S')  OK      ${#OK[@]} ok      ($MODE_LABEL)" >>"$HEALTH_LOG"
else
  echo "$(date '+%Y-%m-%d %H:%M:%S')  FAILED  ${FAILED[*]}  ($MODE_LABEL) -> $COMBINED_LOG" >>"$HEALTH_LOG"
fi

# Failures go to Discord #alerts so a broken run is noticed the same day rather
# than quietly serving stale numbers. Best effort: the failure is already in
# HEALTH_LOG, so a Discord outage degrades the alert instead of losing it.
NOTIFY="$HOME/duo-reports/lib/notify.py"
if [[ ${#FAILED[@]} -ne 0 ]] && [[ -r "$NOTIFY" ]]; then
  python3 "$NOTIFY" --title "Shapeshift campaign report FAILED" \
    --body "Failed clients: **${FAILED[*]}**"$'\n\n'"Mode: ${MODE_LABEL}"$'\n'"Log: \`${COMBINED_LOG}\`" \
    --level error >/dev/null 2>&1 || true
fi

[[ ${#FAILED[@]} -eq 0 ]] || exit 1
