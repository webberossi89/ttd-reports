#!/usr/bin/env bash
#
# Publish a client-facing visual monthly report to Cloudflare Pages.
#
#   ./publish_visual_report.sh <client-slug> <YYYY-MM> <path/to/report.html> [favicon-emoji]
#
# Replaces the claude.ai Artifact route: Artifact sharing is Team/Enterprise-only,
# so clients cannot open one. Same reason Wyndham went to Pages in July.
#
# ONE Cloudflare Pages project, shapeshift-reports, holding every client:
#
#   /<client>/            the current month  <- this is the URL you send, it never changes
#   /<client>/YYYY-MM/    that month, archived permanently
#
# WHY THE SOURCE FILE MUST BE WRAPPED
# The report HTML is authored for the Artifact runtime, which supplies
# <!doctype>, <head> and a viewport meta at publish time. Deploy that file raw and
# you get quirks mode (document.compatMode === "BackCompat") and no viewport, so
# phones render it at ~980px and zoom out. This script supplies the wrapper.
#
# WHY published/ IS PERSISTENT
# `wrangler pages deploy` uploads a whole directory as the new deployment. Every
# client and every past month must still be on disk at deploy time or it vanishes
# from the live site. Do not clean this directory.
#
set -euo pipefail

CLIENT="${1:?usage: publish_visual_report.sh <client-slug> <YYYY-MM> <report.html> [emoji]}"
MONTH="${2:?missing month, format YYYY-MM}"
SRC="${3:?missing path to report html}"
EMOJI="${4:-}"

[[ "$MONTH" =~ ^[0-9]{4}-[0-9]{2}$ ]] || { echo "month must be YYYY-MM, got: $MONTH" >&2; exit 1; }
[[ "$CLIENT" =~ ^[a-z0-9-]+$ ]] || { echo "client slug must be lowercase a-z0-9-, got: $CLIENT" >&2; exit 1; }
[[ -f "$SRC" ]] || { echo "no such file: $SRC" >&2; exit 1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE="$ROOT/published"
PROJECT="shapeshift-reports"
TOKEN_FILE="$HOME/mcp/secrets/cloudflare/token.yaml"

[[ -f "$TOKEN_FILE" ]] || { echo "missing $TOKEN_FILE" >&2; exit 1; }
CLOUDFLARE_API_TOKEN="$(grep '^api_token:' "$TOKEN_FILE" | awk '{print $2}')"
export CLOUDFLARE_API_TOKEN

mkdir -p "$SITE/$CLIENT/$MONTH"

SRC="$SRC" EMOJI="$EMOJI" OUT="$SITE/$CLIENT/$MONTH/index.html" python3 <<'PY'
import os, re, urllib.parse

src   = os.environ["SRC"]
emoji = os.environ["EMOJI"]
out   = os.environ["OUT"]
html  = open(src, encoding="utf-8").read()

if "<!doctype" in html[:200].lower():
    open(out, "w", encoding="utf-8").write(html)
    raise SystemExit

# Hoist the fragment's own <title> into the head we are about to build.
m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
title = m.group(1).strip() if m else "Performance Report"
if m:
    html = html[:m.start()] + html[m.end():]

icon = ""
if emoji:
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
           f"<text y='.9em' font-size='90'>{emoji}</text></svg>")
    icon = f'<link rel="icon" href="data:image/svg+xml,{urllib.parse.quote(svg)}">\n'

open(out, "w", encoding="utf-8").write(
    "<!doctype html>\n<html lang=\"en\">\n<head>\n"
    "<meta charset=\"utf-8\">\n"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
    "<meta name=\"robots\" content=\"noindex, nofollow, noarchive, nosnippet\">\n"
    "<meta name=\"googlebot\" content=\"noindex, nofollow\">\n"
    f"<title>{title}</title>\n"
    f"{icon}"
    "<style>body{margin:0;padding:0}img{max-width:100%}</style>\n"
    "</head>\n<body>\n" + html.lstrip("\n") + "\n</body>\n</html>\n"
)
PY

# Current month also serves at /<client>/ so the client's URL never changes.
cp "$SITE/$CLIENT/$MONTH/index.html" "$SITE/$CLIENT/index.html"

# Crawling is deliberately ALLOWED so the X-Robots-Tag noindex below is actually
# read. "Disallow: /" would block the crawl, hide the noindex, and can leave bare
# URLs in the index instead of removing them.
cat > "$SITE/robots.txt" <<'ROB'
User-agent: *
Allow: /
ROB

cat > "$SITE/_headers" <<'HDR'
/*
  X-Robots-Tag: noindex, nofollow, noarchive, nosnippet
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff
HDR

# Neutral root. Deliberately lists no clients: every report shares this hostname,
# so anything here is visible to all of them.
cat > "$SITE/index.html" <<'IDX'
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive, nosnippet">
<title>Shapeshift Marketing &mdash; Client Reporting</title>
<style>
  body { margin:0; min-height:100vh; display:grid; place-items:center;
         background:#F1EFEA; color:#1A1714;
         font-family:ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  main { max-width:34rem; padding:2rem; text-align:center; }
  h1 { font-family:"Iowan Old Style", Palatino, Georgia, serif; font-weight:600; font-size:1.6rem; margin:0 0 .6rem; }
  p { color:#57514A; margin:0; }
  @media (prefers-color-scheme: dark) {
    body { background:#131211; color:#EFEBE3; } p { color:#B3ABA0; }
  }
</style>
</head>
<body><main>
  <h1>Shapeshift Marketing</h1>
  <p>Client reporting. If you were sent a report link, please open the full address you were given.</p>
</main></body>
</html>
IDX

# Without this, Cloudflare Pages answers an unmatched path with an empty 200,
# so a mistyped report link looks like a blank page rather than a wrong address.
# Written out in full rather than sed'd from index.html: an unescaped "&" in a
# sed replacement expands to the whole match and silently duplicates the <title>.
cat > "$SITE/404.html" <<'NF'
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive, nosnippet">
<title>Not found &mdash; Shapeshift Marketing</title>
<style>
  body { margin:0; min-height:100vh; display:grid; place-items:center;
         background:#F1EFEA; color:#1A1714;
         font-family:ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  main { max-width:34rem; padding:2rem; text-align:center; }
  h1 { font-family:"Iowan Old Style", Palatino, Georgia, serif; font-weight:600; font-size:1.6rem; margin:0 0 .6rem; }
  p { color:#57514A; margin:0; }
  @media (prefers-color-scheme: dark) {
    body { background:#131211; color:#EFEBE3; } p { color:#B3ABA0; }
  }
</style>
</head>
<body><main>
  <h1>Not found</h1>
  <p>That address does not match a report. Please check the link you were sent.</p>
</main></body>
</html>
NF

echo "site contents:"
find "$SITE" -name index.html | sed "s|$SITE|  .|" | sort

npx --yes wrangler pages deploy "$SITE" \
  --project-name="$PROJECT" \
  --branch=main \
  --commit-dirty=true

echo
echo "send the client:  https://${PROJECT}.pages.dev/${CLIENT}/"
echo "archived at:      https://${PROJECT}.pages.dev/${CLIENT}/${MONTH}/"
