# Shapeshift Lead Tracker

Pulls WhatConverts leads per Shapeshift client, buckets by channel
(SEO Organic, SEO GBP, PPC, Direct, Referral), and writes per-month
counts into a Google Sheet.

## Layout

```
~/shapeshift-reports/
  lead_tracker/        # engine (this dir)
    pull_wc.py
    write_sheet.py
    run.sh
  clients/
    plitnick/
      config.yaml
      logs/
  .secrets/
    whatconverts.env   # WC_API_TOKEN + WC_API_SECRET
```

## Per-client config

```yaml
display_name: "Plitnick Plumbing and Heating"
wc_creds: ~/shapeshift-reports/.secrets/whatconverts.env
wc_profile_id: 12345                # WhatConverts profile_id for this client
wc_date_field: date_created         # which date drives month bucketing

spreadsheet_id: 1PMxbjV8GeANtw_uPd8pvCjSjIpRYPLxygWirZGkfqiE
tab_name: "Plitnick"
anchor_text: "Month"                # row where Jan..Dec headers live in cols B..M

rows:                                # label in col A → channel key
  "Total Leads":  total
  "SEO - Organic": seo_organic
  "SEO - GBP":     seo_gbp
  "PPC":           ppc
  "Direct":        direct
  "Referral":      referral

# Optional per-client overrides. Replace any channel's rule list entirely.
# Each rule is a list of "all keys must match (substring, case-insensitive)" clauses.
# classification_rules:
#   seo_gbp:
#     - {lead_source: "google", utm_source: "gbp_listing"}
#     - {referrer: "google.com/maps"}
```

## WhatConverts credentials

`~/shapeshift-reports/.secrets/whatconverts.env` (chmod 600):

```
WC_API_TOKEN=...
WC_API_SECRET=...
```

Token + secret are created in WhatConverts → My Account → API.

## Usage

```bash
# Verify the source data first (raw lead inspection):
cd ~/mcp/servers/google-ads
uv run python3 ~/shapeshift-reports/lead_tracker/pull_wc.py \
  --config ~/shapeshift-reports/clients/plitnick/config.yaml \
  --months 2026-04 \
  --sample 3      # dump 3 raw leads to inspect field names

# Dry-run the bucketing only (no sheet write):
uv run python3 ~/shapeshift-reports/lead_tracker/pull_wc.py \
  --config ~/shapeshift-reports/clients/plitnick/config.yaml \
  --months 2026-01 2026-02 2026-03 2026-04

# Dry-run the sheet writer:
uv run python3 ~/shapeshift-reports/lead_tracker/write_sheet.py \
  --config ~/shapeshift-reports/clients/plitnick/config.yaml \
  --months 2026-04 --dry-run

# Write previous month, protecting any non-zero manual entries:
~/shapeshift-reports/lead_tracker/run.sh plitnick

# MTD refresh of current month (overwrites):
~/shapeshift-reports/lead_tracker/run.sh plitnick --current-month
```

## Classification (default rules)

Order: GBP → PPC → SEO Organic → Direct → Referral → unclassified.

| Channel       | Matches when                                                                 |
| ------------- | ---------------------------------------------------------------------------- |
| seo_gbp       | lead_source contains "google business"/"google my business"/"gmb", OR lead_medium = "profile"/"gmb", OR referrer contains "google.com/maps" or "google.com/local", OR utm_source = "gbp" / utm_medium = "gmb" |
| ppc           | lead_medium = cpc/ppc/paid OR lead_source = "adwords"/"google ads"/"bing ads"/"meta ads"/"facebook ads" |
| seo_organic   | lead_medium = "organic" OR lead_source = google/bing/yahoo/duckduckgo (and not GBP) |
| direct        | lead_medium = "direct" OR lead_source = "direct"                             |
| referral      | lead_medium = referral/email/social                                          |
| unclassified  | everything else (review these via `--sample` and tighten rules)              |

Tighten per-client by setting `classification_rules` in config.yaml. The
default rules are first-pass safe; spot-check `--sample` output to see
the exact WhatConverts field strings on your account before locking in.
