# ads_report.yaml retired 2026-08-06

The DENY paid-media report **moved** out of the standalone "Demolition Experts
Monthly Report" workbook (`16MhrAXxhME3vN8apO4oZDWIbM-s856j8cHziw5P96TE`, tab
`2026`) and into the campaign-block layout the other Shapeshift clients use:

> **"Demolition Experts Lead Sheet"** `1o6NYcVJg7tM_oH3WnNDfcoc10E4d2gQK7tOh61Tmid4`,
> tab **`2026 Report`** (gid 1480168108) — the same workbook the client's own lead
> feed writes into on tab `Leads`.

New config: `~/shapeshift-reports/report_clients/demolition-experts-ny/`
New engine: `~/shapeshift-reports/campaign_report/` (shared with Duo).

`ads_report.yaml` was renamed rather than deleted so `ads_report/run-all.sh`
(which globs `clients/*/ads_report.yaml`) stops picking DENY up. Leaving it in
place would have run BOTH reports on every weekly/monthly schedule, writing two
different shapes of the same numbers into two different workbooks.

**The old `2026` tab is left intact and untouched** as the historical record.
It is no longer refreshed. Mr Cheapee still uses the old engine and is unaffected.

## Audit 2026-08-06 — confirmed nothing writes to the old sheet

Grepped `16MhrAXxhME3vN8apO4oZDWIbM-s856j8cHziw5P96TE` across `shapeshift-reports`,
`duo-reports`, `ops`, `AI-Workspaces`, `mcp`, `recnation`: the ONLY hit is this file.

- `shapeshift-ads-report-weekly.vbs` -> `ads_report/run-all.sh` still runs, but the
  glob `clients/*/ads_report.yaml` now matches **mr-cheapee only** (its own workbook
  `120h6Qg9RKFzysSVTciQGJeB0Rv5SXqaqDcAh6ghNqvU`). DENY is skipped.
- `ss-lead-sheet-sync.vbs` writes the `Leads` tab of the Lead Sheet, not this sheet.
- `shapeshift-monthly-lead-tracker` writes tab "Demolition Experts NY" in the shared
  tracker `1PMxbjV8...`, which is lead counts by channel, not the PPC report.

**The old `2026` tab is now frozen.** Its August column holds Aug 1-5 MTD written by
hand on 2026-08-06 and will never update again, so it goes stale from here. Anyone
reading it for current numbers should be sent to the `2026 Report` tab in
"Demolition Experts Lead Sheet" instead.

To un-retire: rename `ads_report.yaml.retired-20260806` back to `ads_report.yaml`.
