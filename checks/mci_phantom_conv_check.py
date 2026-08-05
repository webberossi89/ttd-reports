"""Check whether the two mis-attributed MCI Waste calls (2026-07-09) posted as
phantom Google Ads conversions via the "WC All Leads (170414)" upload.

Background: WhatConverts stitched Jared's own web session (gclid from an MCI
AI Max ad click on 2026-07-08, IP 76.49.139.192 = NC, email jaredwebber1989@
gmail.com) onto two real existing-customer support calls from +16072428908
(Binghamton NY). Those calls carry that gclid, so the WC->Google Ads upload
would credit the AI Max campaign for them.

This script re-queries the MCI account and reports:
  1. WC All Leads (170414) conversions by campaign/day (07-08..today).
  2. Whether the specific gclid is a click on the AI Max campaign.
  3. The two WhatConverts leads' current state (email / quotable / gclid).

Read-only. Appends a timestamped report to mci_phantom_conv_check.log.

Usage: /home/jared/mcp/servers/google-ads/.venv/bin/python mci_phantom_conv_check.py
"""
import base64
import datetime
import pathlib
import urllib.request

from google.ads.googleads.client import GoogleAdsClient

YAML = "/home/jared/mcp/secrets/google-ads/ttd.yaml"
MCI_CID = "9827039205"
LOGIN_CID = "5199864700"
GCLID = "CjwKCAjw6rfSBhAqEiwA_yocpgCD0eyN8n9xcF2z9-Tyt9kwhEuJw-wCHq4uhtZsD1zwUNHyIGrQ7xoCQUkQAvD_BwE"
LEAD_IDS = ("245871181", "245826726")
WC_CREDS = "/home/jared/shapeshift-reports/.secrets/whatconverts.env"
LOG = pathlib.Path(__file__).with_name("mci_phantom_conv_check.log")


def out(fh, msg=""):
    print(msg)
    fh.write(msg + "\n")


def gaql(client, cid, query):
    ga = client.get_service("GoogleAdsService")
    return list(ga.search(customer_id=cid, query=query))


def wc_creds():
    tok = sec = None
    for line in pathlib.Path(WC_CREDS).read_text().splitlines():
        line = line.strip()
        if "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if k.strip().lower() in ("api_token", "wc_api_token"):
            tok = v
        elif k.strip().lower() in ("api_secret", "wc_api_secret"):
            sec = v
    return tok, sec


def wc_get(lead_id):
    tok, sec = wc_creds()
    auth = base64.b64encode(f"{tok}:{sec}".encode()).decode()
    req = urllib.request.Request(
        f"https://app.whatconverts.com/api/v1/leads/{lead_id}",
        headers={"Authorization": f"Basic {auth}"},
    )
    import json
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    return d.get("leads", [d])[0] if isinstance(d, dict) and "leads" in d else d


def main():
    today = datetime.date.today().isoformat()
    client = GoogleAdsClient.load_from_storage(YAML)
    client.login_customer_id = LOGIN_CID

    with LOG.open("a") as fh:
        out(fh, "=" * 70)
        out(fh, f"MCI phantom-conversion check run {datetime.datetime.now().isoformat(timespec='seconds')}")
        out(fh, "=" * 70)

        # 1. WC All Leads conversions by campaign/day
        out(fh, "\n[1] WC All Leads (170414) conversions 2026-07-08..today, by campaign:")
        rows = gaql(client, MCI_CID, f"""
            SELECT campaign.name, segments.conversion_action_name, segments.date, metrics.all_conversions
            FROM campaign
            WHERE segments.date BETWEEN '2026-07-08' AND '{today}'
              AND segments.conversion_action_name = 'WC All Leads (170414)'
              AND metrics.all_conversions > 0
            ORDER BY segments.date
        """)
        if not rows:
            out(fh, "   (none)")
        for r in rows:
            out(fh, f"   {r.segments.date}  {r.metrics.all_conversions:>4}  {r.campaign.name}")

        # 2. Is the gclid an AI Max click? (scan 07-08..today, one day at a time)
        out(fh, "\n[2] gclid origin (click_view):")
        d0 = datetime.date(2026, 7, 8)
        found = False
        while d0 <= datetime.date.today():
            ds = d0.isoformat()
            try:
                cr = gaql(client, MCI_CID, f"""
                    SELECT click_view.gclid, campaign.name, segments.date
                    FROM click_view
                    WHERE segments.date = '{ds}' AND click_view.gclid = '{GCLID}'
                """)
                for r in cr:
                    found = True
                    out(fh, f"   click {r.segments.date}  campaign={r.campaign.name}")
            except Exception as e:
                out(fh, f"   {ds}: query error {e}")
            d0 += datetime.timedelta(days=1)
        if not found:
            out(fh, "   gclid not found as a click in this window")

        # 3. WhatConverts lead state
        out(fh, "\n[3] WhatConverts lead state:")
        for lid in LEAD_IDS:
            try:
                l = wc_get(lid)
                out(fh, f"   lead {lid}: email={l.get('contact_email_address')!r} "
                        f"quotable={l.get('quotable')!r} gclid_present={bool(l.get('gclid'))}")
            except Exception as e:
                out(fh, f"   lead {lid}: WC fetch error {e}")

        out(fh, "\nInterpretation: if [1] shows AI Max conversions on 07-08 that")
        out(fh, "exceed real leads, and [3] still shows the gclid on these calls,")
        out(fh, "the phantom conversions have posted. Fix: exclude IP 76.49.139.192")
        out(fh, "in WhatConverts + GA4, and remove the email in the WC dashboard.\n")


if __name__ == "__main__":
    main()
