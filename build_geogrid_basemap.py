#!/usr/bin/env python3
"""
Compose a Web Mercator basemap for a geo-grid scan, as a single baked image.

  python3 build_geogrid_basemap.py <out-dir> <scan.json> [scan.json ...]

Writes, into <out-dir>:
  basemap-light.html / basemap-dark.html   pages to screenshot (tiles positioned)
  bounds.json                              exact geo extent of the rendered image

Why a baked image rather than a live map:
The reports archive permanently at /<client>/YYYY-MM/, so a runtime dependency on a
tile server means blank maps in old reports the day that server changes its URL scheme.
Screenshotting the tile mosaic once and embedding it as a data URI keeps every archived
report self-contained and printable. (The Artifact CSP used to block tiles outright;
that constraint is gone now the reports are on Cloudflare Pages, but durability is a
better reason to bake them than CSP ever was.)

Tiles: CARTO basemaps, which are designed to sit under data overlays and come in
matched light/dark. Attribution to OpenStreetMap and CARTO is REQUIRED and is rendered
in the report caption.
"""
import json, math, os, sys

TILE = 256
TARGET_W = 660          # rendered px; ~2x the on-screen size, so it stays crisp
PAD_FRAC = 0.06         # breathing room so edge pins do not sit on the border

STYLES = {
    "light": "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    "dark":  "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
}


def merc_y(lat):
    """Web Mercator y, in the same normalised space as lon/360."""
    s = math.sin(math.radians(lat))
    return 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


def merc_x(lng):
    return (lng + 180.0) / 360.0


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    out_dir, scans = sys.argv[1], sys.argv[2:]
    os.makedirs(out_dir, exist_ok=True)

    lats, lngs = [], []
    for f in scans:
        for p in json.load(open(f))["points"]:
            lats.append(p["lat"])
            lngs.append(p["lng"])
    if not lats:
        sys.exit("no points found in scans")

    lat_min, lat_max = min(lats), max(lats)
    lng_min, lng_max = min(lngs), max(lngs)
    pad_lat = (lat_max - lat_min) * PAD_FRAC
    pad_lng = (lng_max - lng_min) * PAD_FRAC
    lat_min, lat_max = lat_min - pad_lat, lat_max + pad_lat
    lng_min, lng_max = lng_min - pad_lng, lng_max + pad_lng

    # Zoom such that the padded box is about TARGET_W wide.
    span_x = merc_x(lng_max) - merc_x(lng_min)
    zoom = max(0, min(18, round(math.log2(TARGET_W / (span_x * TILE)))))
    world = TILE * (2 ** zoom)

    # Pixel box of the padded bbox in world pixel space.
    px0, px1 = merc_x(lng_min) * world, merc_x(lng_max) * world
    py0, py1 = merc_y(lat_max) * world, merc_y(lat_min) * world   # y grows southward
    width, height = round(px1 - px0), round(py1 - py0)

    tx0, tx1 = int(px0 // TILE), int((px1 - 1e-9) // TILE)
    ty0, ty1 = int(py0 // TILE), int((py1 - 1e-9) // TILE)
    off_x, off_y = px0 - tx0 * TILE, py0 - ty0 * TILE

    for style, url in STYLES.items():
        imgs = []
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                src = url.format(z=zoom, x=tx, y=ty, r="@2x")
                left = (tx - tx0) * TILE - off_x
                top = (ty - ty0) * TILE - off_y
                imgs.append(
                    f'<img src="{src}" width="{TILE}" height="{TILE}" '
                    f'style="position:absolute;left:{left:.2f}px;top:{top:.2f}px">'
                )
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;padding:0;background:#fff}"
            f"#m{{position:relative;width:{width}px;height:{height}px;overflow:hidden}}"
            "img{display:block}</style></head><body>"
            f"<div id='m'>{''.join(imgs)}</div></body></html>"
        )
        open(os.path.join(out_dir, f"basemap-{style}.html"), "w").write(html)

    json.dump(
        {
            "latMin": lat_min, "latMax": lat_max,
            "lngMin": lng_min, "lngMax": lng_max,
            "zoom": zoom, "width": width, "height": height,
            "tiles": (tx1 - tx0 + 1) * (ty1 - ty0 + 1),
        },
        open(os.path.join(out_dir, "bounds.json"), "w"),
        indent=2,
    )
    print(f"zoom {zoom}  image {width}x{height}px  "
          f"{(tx1-tx0+1)*(ty1-ty0+1)} tiles/style")
    print(f"bbox  lat {lat_min:.6f}..{lat_max:.6f}  lng {lng_min:.6f}..{lng_max:.6f}")


if __name__ == "__main__":
    main()
