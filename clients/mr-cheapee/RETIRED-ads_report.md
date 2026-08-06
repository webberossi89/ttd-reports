# ads_report.yaml retired 2026-08-06

The Mr Cheapee paid-media report **moved** out of the standalone "Mr Cheapee
Monthly Report" workbook (`120h6Qg9RKFzysSVTciQGJeB0Rv5SXqaqDcAh6ghNqvU`, tab
`2026`) and into the campaign-block layout every other Shapeshift client uses:

> **"Mr Cheapee Inc Lead Sheet"** `1Xu3ec74sKxqCBlPsb98rx88PYFADPBmCWKrwG5MJ33Y`,
> tab **`2026 Report`** (gid 1939694895) — the same workbook the client's own lead
> feed writes into on tabs `April` / `Web Form Leads`.

New config: `~/shapeshift-reports/report_clients/mr-cheapee/`
New engine: `~/shapeshift-reports/campaign_report/` (shared with Duo).

`ads_report.yaml` was renamed rather than deleted so `ads_report/run-all.sh`
(which globs `clients/*/ads_report.yaml`) stops picking Mr Cheapee up. Leaving it
in place would have run BOTH reports on every weekly/monthly schedule, writing two
different shapes of the same numbers into two different workbooks.

## Why the move was worth doing

The old layout had one "Google Ads Search" block averaging every Search campaign
together. That stopped meaning anything the moment AI Max launched on 6/08: for
July it blended a campaign throttled to $1.00/day ($173.44, 13 clicks) with one
spending $1,397.04 on 217 clicks, and reported a single CPL for both. The new tab
gives each campaign its own block, so the throttle is visible instead of averaged
away.

It also fixed two reporting defects on the way through:

- **Meta was being counted as Google paid search** (audit item G3). The old
  channel rule keyed on `lead_medium: cpc`, which Meta also uses. The new config
  filters on `lead_source: google`, so the 48 Meta leads in 2026 cannot leak in.
- **`AI Max` / `AI+Max` was counted as two campaigns** (audit item G8). WhatConverts
  stores both forms (30 and 18 leads in 2026). `normalize_campaign` folds them into
  one block, so the campaign is no longer undercounted by a third.

## Mr Cheapee was the LAST client on the old engine

`ads_report/run-all.sh` now globs **zero** configs. The Windows scheduled task
`shapeshift-ads-report-weekly` (`~/ops/vbs-backup/shapeshift-ads-report-weekly.vbs`
-> `ads_report/run-all.sh`) will still fire, find no clients, and exit 0 doing
nothing. **It should be disabled** — it is now pure noise in the logs. Left enabled
for now because disabling a Windows scheduled task is a Jared action, not a WSL one.

## Audit 2026-08-06 — confirmed nothing else writes to the old sheet

Grepped `120h6Qg9RKFzysSVTciQGJeB0Rv5SXqaqDcAh6ghNqvU` across `shapeshift-reports`,
`duo-reports`, `ops`, `AI-Workspaces`, `mcp`, `recnation`. Only two hits, both
documentation: this file's DENY equivalent, and the config now renamed.

- `ss-lead-sheet-sync.vbs` writes the lead-feed tabs of the Lead Sheet, not this sheet.
- `shapeshift-monthly-lead-tracker` writes tab "Mr Cheapee" in the shared tracker
  `1PMxbjV8GeANtw_uPd8pvCjSjIpRYPLxygWirZGkfqiE` — lead counts by channel, not the
  PPC report. `clients/mr-cheapee/config.yaml` still drives it and is unaffected.

**The old `2026` tab is left intact and untouched** as the historical record, and is
no longer refreshed. Its July column holds the corrected G3 figures written by hand
on 2026-08-06 (51 leads, CPL $30.79); its June column is still on the old basis and
includes 17 Meta leads. It goes stale from here. Anyone reading it for current
numbers should be sent to the `2026 Report` tab in "Mr Cheapee Inc Lead Sheet".

To un-retire: rename `ads_report.yaml.retired-20260806` back to `ads_report.yaml`.
