# shapeshift-reports

Reporting tooling for Shapeshift Marketing clients. Lives on the WSL box and is
mirrored here so it is reachable from any machine.

## Client-facing visual monthly reports

    ./publish_visual_report.sh <client-slug> <YYYY-MM> <report.html> [favicon-emoji]

Publishes to the single Cloudflare Pages project `shapeshift-reports`:

| Path | Meaning |
|---|---|
| `/<client>/` | the current month — this is the URL given to the client, it never changes |
| `/<client>/YYYY-MM/` | that month, archived permanently |

Live today: `/ford-piano/` and `/h-and-h/`.

### `published/` IS THE SITE. DO NOT CLEAN IT.

`wrangler pages deploy` uploads a whole directory as the new deployment. Every client
and every past month must be present on disk at deploy time or **it disappears from the
live site**. That is why `published/` is committed here rather than treated as build
output: it is the only copy of what is live.

### The source HTML is an Artifact fragment

Report HTML is authored for the claude.ai Artifact runtime, which supplies `<!doctype>`,
`<head>` and a viewport meta at publish time. Deployed raw it renders in quirks mode with
no viewport, so phones show it ~980px wide and zoomed out. `publish_visual_report.sh`
builds that wrapper. Verify `document.compatMode === "CSS1Compat"` after any deploy — the
fault is invisible in a desktop screenshot.

## Geo-grid basemaps

    python3 build_geogrid_basemap.py <out-dir> <scan.json> [scan.json ...]

Composes a Web Mercator basemap from CARTO tiles (light + dark) and writes the exact geo
bounds. There is no Pillow, pip, ImageMagick or sharp on the WSL box, so the tile mosaic
is stitched by screenshotting it with `dev-browser` and the PNG is base64-embedded into
the report. Baked in rather than fetched at view time, because reports archive permanently
and a live tile dependency means blank maps in old reports the day a URL scheme changes.
Attribution to OpenStreetMap and CARTO is required and belongs in the report caption.

**Never report a geo-grid ranking from a single scan.** Repeat runs put a phantom
first-place result on a different cell every time, while deep ranks reproduce almost
exactly. Scan 2-3 times and keep only cells present in at least two, using the median.

## Campaign-block Google Ads reports

`campaign_report/` drives the shared Duo engine; per-client config in `report_clients/`.
See `campaign_report/README.md`.

## Credentials

None are stored here. `.secrets/` and every `*.env` are gitignored. The Cloudflare API
token lives at `~/mcp/secrets/cloudflare/token.yaml` on the box that deploys. A fresh
clone cannot deploy until that token exists locally.
