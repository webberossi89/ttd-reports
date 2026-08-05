# Shapeshift campaign-block monthly reports

Internal monthly paid-media reports for Shapeshift Marketing clients, in the
same shape as the Duo Digital ones: **one block per campaign**, not per channel.
A channel-level "Google Ads Search" row averages every campaign into a number
that stops meaning anything the moment an account runs more than one.

Engine is **shared with Duo** (`~/duo-reports/lead_tracker/`). Only the clients
root differs, so a Shapeshift client can never be picked up by a Duo scheduled
task or vice versa.

| | |
|---|---|
| Client configs | `~/shapeshift-reports/report_clients/<client>/` |
| Engine | `~/duo-reports/lead_tracker/write_sheet.py` |
| Tab builder | `~/duo-reports/lead_tracker/build_campaign_tab.py` |
| Runners | `run.sh` / `run-all.sh` in this directory |
| Logs | per-client `logs/`, combined `~/shapeshift-reports/logs/campaign-report-*.log`, one-liner health `~/shapeshift-reports/logs/campaign-report-health.log` |

Live clients:

- **ford-piano** (sheet `1aJTo20E3EPnjZb9g5fR2FNmu3sr-plsz0ByhV3ZGUow`, tab
  `2026 Report`, in "Ford Piano Lead Sheet").
- **h-and-h** (sheet `1YQfyEiv26NVV_sdyYJbq8H3pcr9WYkSW_E53FIcj-uI`, tab
  `2026 Report`, in "H & H Signature Renovations Lead Sheet"). Onboarded
  2026-08-05, backfilled from 2026-05 (campaign launched 5/01).

## Running it

```bash
~/shapeshift-reports/campaign_report/run.sh ford-piano                  # prev month, close-out
~/shapeshift-reports/campaign_report/run.sh ford-piano 2026-07          # a specific month
~/shapeshift-reports/campaign_report/run.sh ford-piano --current-month  # MTD, force-overwrite
~/shapeshift-reports/campaign_report/run-all.sh --current-month         # every client, MTD
```

Scheduled (Windows Task Scheduler, staggered after the other report jobs):

- **Shapeshift campaign report daily MTD** — daily 10:10 → `run-all.sh --current-month`
- **Shapeshift campaign report monthly** — 3rd of month 10:20 → `run-all.sh` (month just ended)

Both go through `~/ops/run-alert.sh`, so a failure posts to Discord #alerts.

## Adding a campaign to an existing client

`campaigns.yaml` is the one source of truth: it generates both the sheet layout
and the `sections:` block of `config.yaml`, so the two cannot drift.

```bash
cd ~/mcp/servers/google-ads
uv run python3 ~/duo-reports/lead_tracker/build_campaign_tab.py \
  --clients-root ~/shapeshift-reports/report_clients \
  --client ford-piano add <campaign_id> --title "SEARCH | THEME" --apply
```

Drop `--apply` to preview. A rebuild preserves existing values by (block title,
row label, month), so blocks can be added, reordered, or retitled without losing
history. `--title` is worth passing on Shapeshift accounts: campaign names there
read "Ford Piano - Piano Repair & Rebuilding - shapeshift - 17.06.2026", with no
pipes for the title deriver to split on.

## Onboarding a new client

1. `mkdir ~/shapeshift-reports/report_clients/<client>` and copy `ford-piano/`'s
   `config.yaml` + `campaigns.yaml` as the template.
2. Swap in `search_pmax_video_account` (and `lsa_account`, same CID if the
   account has no LSA), `spreadsheet_id`, `tab_name`, WhatConverts `profile_id`.
   `ads_creds` is `ttd.yaml` for SSM clients reached through the TTD MCC.
3. `sheets_creds` only if the sheet is not shared with **jared@goduo.co**. Ford
   Piano's is owned by jaredwebber1989 and shared with the service account
   `ga4-reader@ttd-analytics-500221`, so it sets it; a goduo-shared sheet omits
   the key and uses the default OAuth token.
4. Create the tab in the workbook (an empty tab is fine), then
   `build_campaign_tab.py ... build --apply`.
5. Backfill only the months the campaign actually ran:
   `write_sheet.py --config <config> --months 2026-07 2026-08`.
   **Leave pre-launch months blank, never zeroed** — `$0.00` across a live
   looking row reads as "we ran and spent nothing", which is a different and
   untrue claim.
6. Hand-reconcile one closed month and put it in `validation:`. The engine
   refuses to write if it stops matching, which is the point.

## Where the lead numbers come from

Spend, clicks, and impressions always come from Google Ads. Lead counts come
from whichever source can actually split form vs phone on that account:

- **Google Ads conversion actions** (`conversion_action_buckets`) when the
  account has clean, non-duplicated form and phone actions. This is the Duo
  default.
- **WhatConverts** (`wc_lead_source`) when it cannot. Ford Piano is this case:
  its only working lead action, `WC All Leads (168410)`, is a single mixed
  bucket of forms and calls, the GA4 twins record zero, and `Calls from ads`
  duplicates `Google Ads Call Extension`.
- **Both, summed** (`mode: add`) when neither source sees every lead. Ford
  Piano again: WhatConverts sees website leads (forms + dynamic-number-pool
  calls) but never a call placed straight from the ad's call asset, because
  that call never touches the site and carries no gclid. Google Ads counts
  exactly those, on `Google Ads Call Extension`. So the config buckets that one
  action and adds WhatConverts on top. Nothing is counted twice: `WC All Leads`
  is deliberately NOT bucketed, since it is the same set WhatConverts supplies.

**Sum only sources that cannot see the same lead.** Before setting `mode: add`,
name for each source exactly which leads it sees and prove the two lists are
disjoint. Getting this wrong doubles the lead count silently.

For a WhatConverts-sourced client, set **both** `require_gclid: true` and
`lead_mediums: [cpc, ppc, paid]`, plus `unique_only: true` if the row has to
reconcile with Google Ads (WhatConverts uploads only unique leads, so a repeat
caller pushes the sheet above the Conversions column):

- WhatConverts labels a lead google/cpc from session data alone, so robocalls
  dialling the call-extension number land in the paid bucket. Ford Piano, July
  2026: 29 google/cpc leads, only 20 with a gclid, and the 9 without included
  the 5 fake "Google Ads Team" calls from +1 313-483-9122.
- A gclid outlives the click that set it, so a repeat visitor arriving later
  from the Google Business Profile still carries one. gclid alone would book
  that as a paid lead (it happened on 2026-08-04).

Ford Piano's July 2026 reconciles lead by lead: **20 leads = 18 unique
gclid-bearing WhatConverts leads (6 form + 12 phone) + 2 `Google Ads Call
Extension` calls**, and Google Ads independently recorded 18 on `WC All Leads`
plus those same 2.

### When the Google Ads UI and the sheet disagree, check for a duplicated action

Ford Piano's July reads **21 in the Google Ads UI and 20 in the sheet**. The
difference is one real phone call counted twice: on 2026-07-28 both
`Google Ads Call Extension` (WhatConverts' upload) and `Calls from ads`
(Google's own AD_CALL) fired once, and WhatConverts logged exactly ONE call to
the call-extension number that day. `Calls from ads` is therefore left out of
the buckets. Two actions that both watch the call asset will overlap whenever a
call runs past the AD_CALL duration threshold, so on any account carrying both,
bucket one and only one of them.

**`require_gclid` is not universal, check the account before copying it.** On
H&H it would have done the opposite of its job: every one of our own test leads
carries a fake gclid (`TESTGCLID123`, `TTDTEST_20260731`), so they all pass the
check, while the one genuine May phone call carries none and would be dropped.
That client uses `campaign_sections` instead, matching on the real campaign's
utm_campaign, which excludes tests fired under an invented campaign string.

### Our own test leads count as real leads

Every tracking or email-deliverability test we fire at a client site lands in
WhatConverts as an ordinary lead with `lead_source` google and `lead_medium`
cpc. Nothing in the data marks it as ours. Five of the eight paid leads on H&H's
2026 record were tests, and reporting the raw bucket would have shown July as a
2-lead month when the true figure was 0.

`campaign_sections` catches the ones fired under an invented utm_campaign. It
cannot catch a test fired against the real campaign string. For those, flag the
lead **spam** in WhatConverts: the engine already skips spam-flagged leads, and
it cleans the client-visible lead feed at the same time.

Audit any client before onboarding it. Tells: fake gclid, an
`@thomastowndigital.com` or `@example.com` address, a contact name starting
`TEST SUBMIT`, a `lead_campaign` containing `test`.

Known and accepted: WhatConverts buckets by lead date, Google Ads by click date,
so a lead either side of a month boundary can land in different months in the
two systems.
