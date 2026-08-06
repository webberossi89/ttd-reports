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
- **plitnick** (sheet `19xwER2sOuBFrZLbzhg5YTkyoHuihNhmnpbSlmzgTUg8`, tab
  `2026 Report`, in "Plitnick Lead Sheet"). Four campaign blocks.
- **365-pools** (sheet `1AZT3FdCG595Rl-eYXLkKXXfOqrWEpLe9jtsplfSrr0Y`, tab
  `2026 Report`, in "365 Pool Service Lead Sheet", alongside the `Sheet1` lead
  sync). Onboarded 2026-08-05, backfilled Jan-Jul. Two blocks, Search and PMax.
  Same two-source `mode: add` shape as Ford Piano: `require_gclid` is the exact
  separator on this account because not one of the 45 July ad-call-asset calls
  carries a gclid, and every website lead does.
- **plitnick** (sheet `19xwER2sOuBFrZLbzhg5YTkyoHuihNhmnpbSlmzgTUg8`, tab
  `2026 Report`, in "Plitnick Lead Sheet"). Four campaigns.
- **demolition-experts-ny** (sheet `1o6NYcVJg7tM_oH3WnNDfcoc10E4d2gQK7tOh61Tmid4`,
  tab `2026 Report`, in "Demolition Experts Lead Sheet" — the same workbook the
  client's own lead feed writes into on tab `Leads`). Onboarded 2026-08-06,
  backfilled Jan-Aug. **Four blocks**: two Search, one PMax, one LSA. The LSA
  campaign is a block rather than an LSA section because it genuinely spent
  ($187.80, February only); leaving it out surfaced that in the QA row.
  **Its `require_gclid` means something different from every other client here** —
  this account has no "Google Ads Call Extension" number in WhatConverts, so
  gclid separates "landed on the site" from "called from the ad", not form from
  call. Read the config header before touching it. Replaces the old
  channel-block `ads_report.yaml`, now retired.
- **mr-cheapee** (sheet `1Xu3ec74sKxqCBlPsb98rx88PYFADPBmCWKrwG5MJ33Y`, tab
  `2026 Report`, in "Mr Cheapee Inc Lead Sheet" — the same workbook the client's
  own lead feed writes into on tabs `April` / `Web Form Leads`). Onboarded
  2026-08-06, backfilled Jan-Aug. **Three blocks**: two Search, one LSA. LSA is a
  major spender here ($7,254.58 in 2026), not a footnote. Same two-source
  `mode: add` shape, and on this account the ad-call-asset number DOES have its
  own WhatConverts `phone_name` ("Google Call Asset"), so `require_gclid` splits
  the sources cleanly. **Gotcha:** the phone bucket needs the FULL action name
  `Google Ads Call Extension (WC Setup)` — matching is exact set membership, and
  the bare "Google Ads Call Extension" used on DENY silently yields ads=0.
  Replaces the old channel-block `ads_report.yaml`, now retired — Mr Cheapee was
  the LAST client on that engine, so `ads_report/run-all.sh` now globs zero
  configs and the `shapeshift-ads-report-weekly` task should be disabled.
- **mci-waste** (sheet `1N9oB7RrceWlGfm2qtq_0wa1xSecXu5pZk40b-Il9CR4`, tab
  `2026 Report`, in "MCI Waste Lead Sheet" — the same workbook the client's own
  lead feed writes into on tab `All Leads`). Onboarded 2026-08-06, backfilled
  Jun-Aug; both campaigns launched 6/24 so there is nothing before June. Two
  Search blocks, the second running AI Max keyword expansion. Same two-source
  `mode: add` shape as Ford Piano and 365 Pools, and `require_gclid` is again
  the exact separator: all 28 "Google Call Asset" calls Jan-Aug carry no gclid,
  every website lead does.
  **It is the only client on `conversion_metric: all_conversions`** — its
  bucketed action was deliberately made secondary on 2026-08-06, so
  `conversions` reads 0 for it. Read the config header before touching it.
  **It is also the only client NOT on service-account auth**, because the
  workbook is not shared with `ga4-reader@ttd-analytics-500221`.
- **south-coast-demo** (sheet `1HCf0YVZQis-bxT6HM77lHr5SZU6qpaObPmuL_oz30Y8`,
  tab `2026 Report`, in "South Coast Demo Lead Sheet" — the same workbook the
  client's own lead feed writes into on tab `Sheet1`). Onboarded 2026-08-05,
  backfilled from 2026-01 for Demolition; GPR & Concrete Cutting is blank
  before July because it launched 7/02.

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

   **On a client whose campaigns launched at different times, one backfill
   cannot do this for you.** `write_sheet.py` takes one month list for the
   whole config, and a campaign with no data in a requested month gets a real
   `0` written, not a skip. So backfill the full range, then `values.batchClear`
   the younger campaign's pre-launch INPUT cells. Clear only the input rows;
   the rate rows between them are formulas and clearing those destroys the
   block. On south-coast-demo that was rows 17/18/20/22/23 (Clicks,
   Impressions, Cost, Form Leads, Phone Leads) across cols B:G for Jan-Jun.
   The formulas already guard blanks — `IF(B18=0,"",…)` and `N()` on CPL — so
   the whole block renders empty once the inputs are gone.
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

### Multi-block clients show $0.00 in pre-launch months, single-block ones show blank

Found 2026-08-06 onboarding mci-waste. Not a config error, and not something a
client config can fix.

The TOTAL PAID MEDIA rows are generated as a sum of the campaign blocks:

- **One block** → `=B5`. A plain reference to an empty cell returns empty, so a
  pre-launch month renders **blank**. H&H (launched 2026-05) shows blank
  Jan-Apr.
- **Two or more blocks** → `=B5+B17`. Arithmetic coerces empty to 0, so the same
  pre-launch month renders **`0` / `$0.00`**. mci-waste (launched 2026-06-24)
  shows `$0.00` Jan-May in TOTAL PAID MEDIA and in `Sum Of Campaign Blocks`.

Only the `Total Leads` row is guarded (`=IF(AND(B34="",B35=""),"",B34+B35)`),
which is the blank-not-zero fix applied to the Duo tabs on 2026-08-05. Clicks,
Impressions, Cost, Form Leads and Phone Leads are not.

That is the same "we ran and spent nothing" misread the onboarding steps warn
about, just one level up from the campaign blocks. **Fix is to wrap the other
TOTAL rows in the same guard** in `build_campaign_tab.py`. Left undone
deliberately: it changes generated formulas for every Duo and Shapeshift client
at once, so it wants its own change window and a before/after cell diff, not a
drive-by at the end of an unrelated session.

Do **not** patch it by clearing the cells by hand — they are formulas, and the
next `build` regenerates them, which is exactly the drift `campaigns.yaml`
exists to prevent.
