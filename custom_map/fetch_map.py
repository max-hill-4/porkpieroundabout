"""Pull Esri World Imagery tiles for a lat/lon box and stitch into one PNG.
No API key required for light use. Mercator-projected satellite tiles.
"""
import io
import math
import os
import sys
import time
import urllib.request
from PIL import Image

CENTER = (52.596864, -1.141572)  # (lat, lon) from the OSM link
HALF_BOX_M = 200.0                 # 400m x 400m centered on the point
ZOOM = 19                          # Esri World Imagery — max zoom with data for this area
OUTPUT_POT = 4096                  # power-of-two output size; sidesteps three.js NPOT downscale

TILE_SIZE = 256
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def latlon_to_meters(lat, lon):
    # Web Mercator in meters
    r = 6378137.0
    x = math.radians(lon) * r
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * r
    return x, y


def meters_to_latlon(x, y):
    r = 6378137.0
    lon = math.degrees(x / r)
    lat = math.degrees(2 * math.atan(math.exp(y / r)) - math.pi / 2)
    return lat, lon


def meters_per_pixel(lat, zoom):
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)


def lonlat_to_tile_xy(lon, lat, zoom):
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def main():
    lat, lon = CENTER
    # Build a square box in meters around the center
    cx, cy = latlon_to_meters(lat, lon)
    x_min, x_max = cx - HALF_BOX_M, cx + HALF_BOX_M
    y_min, y_max = cy - HALF_BOX_M, cy + HALF_BOX_M

    # Convert box corners to lat/lon
    lat_min, lon_min = meters_to_latlon(x_min, y_min)
    lat_max, lon_max = meters_to_latlon(x_max, y_max)

    # Tile range covering the box. In Web Mercator, tile y increases southward
    # so the NORTH edge has the SMALLER y tile index.
    tx_west, ty_north = lonlat_to_tile_xy(lon_min, lat_max, ZOOM)
    tx_east, ty_south = lonlat_to_tile_xy(lon_max, lat_min, ZOOM)
    tx_min_i, tx_max_i = int(math.floor(tx_west)), int(math.floor(tx_east))
    ty_top_i, ty_bot_i = int(math.floor(ty_north)), int(math.floor(ty_south))

    cols = tx_max_i - tx_min_i + 1
    rows = ty_bot_i - ty_top_i + 1
    print(f"Box: lat[{lat_min:.6f},{lat_max:.6f}] lon[{lon_min:.6f},{lon_max:.6f}]")
    print(f"Zoom {ZOOM}: {cols}x{rows} tiles ({cols * TILE_SIZE}x{rows * TILE_SIZE} px)")

    mosaic = Image.new("RGB", (cols * TILE_SIZE, rows * TILE_SIZE))
    for i in range(rows):
        for j in range(cols):
            tx = tx_min_i + j
            ty = ty_top_i + i
            url = ESRI.format(z=ZOOM, y=ty, x=tx)
            req = urllib.request.Request(url, headers={"User-Agent": "sketchbook-map-fetch/1.0"})
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=30) as r:
                        tile = Image.open(io.BytesIO(r.read()))
                    mosaic.paste(tile, (j * TILE_SIZE, i * TILE_SIZE))
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"  failed tile ({tx},{ty}): {e}", file=sys.stderr)
                    else:
                        time.sleep(1)
            time.sleep(0.05)  # be gentle
    out = os.path.join(OUT_DIR, "satellite_raw.png")
    src_w, src_h = mosaic.size
    if OUTPUT_POT:
        # Resize to power-of-two so three.js doesn't downscale NPOT textures
        # (old three 0.113 in WebGL1 mode shrinks 1792x1536 to 1024x1024).
        mosaic = mosaic.resize((OUTPUT_POT, OUTPUT_POT), Image.LANCZOS)
    mosaic.save(out)
    print(f"saved {out} ({mosaic.size[0]}x{mosaic.size[1]})")

    # Resolution in m/px for reference
    res = meters_per_pixel(lat, ZOOM)
    # Ground extent of the *stitched source* (before POT resize). The POT resize
    # just samples this up or down — the ground extent is determined by the
    # source tiles, not the output pixels.
    ground_w_m = src_w * res
    ground_h_m = src_h * res
    print(f"~{res:.3f} m/px source; ground extent {ground_w_m:.1f}m x {ground_h_m:.1f}m")

    import json
    meta = {
        "zoom": ZOOM,
        "center_lat": lat,
        "center_lon": lon,
        "half_box_m": HALF_BOX_M,
        "m_per_px": res,
        "source_px": [src_w, src_h],
        "output_px": [mosaic.size[0], mosaic.size[1]],
        "ground_w_m": ground_w_m,
        "ground_h_m": ground_h_m,
    }
    with open(os.path.join(OUT_DIR, "satellite_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print("wrote satellite_meta.json")


if __name__ == "__main__":
    main()