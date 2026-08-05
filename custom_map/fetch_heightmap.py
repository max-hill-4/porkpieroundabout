"""Pull a DEM subset from OpenTopography (SRTM GL3, 30m globally) for a lat/lon box
and convert it to a Blender-friendly 16-bit PNG heightmap.

Needs an OpenTopography API key: https://portal.opentopography.org/myop.php
Free for academic / personal use. Rate limited (~200 calls/day).
"""
import io
import math
import os
import subprocess
import sys
import urllib.request
from PIL import Image

# Must match the box used for the satellite fetch (custom_map/fetch_map.py).
CENTER = (52.596864, -1.141572)  # (lat, lon)
HALF_BOX_M = 200.0                 # 400m x 400m — the roundabout area for the heightmap output
# OpenTopography refuses tiny boxes ("selected area is too small"), so we fetch
# a 1km box for the DEM and crop down to the roundabout area later.
OP_HALF_BOX_M = 600.0              # 1.2km x 1.2km fetch region
OP_TOPO_KEY = os.environ.get("OPENTOPO_KEY") or "fda0950299a143663769f89331d044db"

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def latlon_to_meters(lat, lon):
    r = 6378137.0
    x = math.radians(lon) * r
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * r
    return x, y


def meters_to_latlon(x, y):
    r = 6378137.0
    lon = math.degrees(x / r)
    lat = math.degrees(2 * math.atan(math.exp(y / r)) - math.pi / 2)
    return lat, lon


def fetch_dem_geotiff(lat_min, lat_max, lon_min, lon_max, out_path):
    # OpenTopography REST: global DEM API. SRTM GL3 = 30m global.
    url = (
        "https://portal.opentopography.org/API/globaldem"
        f"?demtype=SRTMGL1"
        f"&south={lat_min}&north={lat_max}&west={lon_min}&east={lon_max}"
        f"&outputFormat=GTiff&API_Key={OP_TOPO_KEY}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "sketchbook-map-fetch/1.0"})
    print(f"fetching DEM: {url}")
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    if len(data) < 1000 or data[:4] == b"<html" or b"<html" in data[:200]:
        # API errors come back as text
        raise RuntimeError(f"OpenTopography error: {data[:500]!r}")
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"saved geotiff: {out_path} ({len(data)} bytes)")


def geotiff_to_heightmap_png(geotiff_path, png_path, target_width=512):
    """Use gdal to read the GeoTIFF and dump a normalized 16-bit PNG.

    Falls back to a manual read via Pillow if gdal is unavailable, but gdal
    handles the nodata fill and georeferencing correctly.
    """
    have_gdal = subprocess.run(["which", "gdal_translate"], capture_output=True).returncode == 0
    if not have_gdal:
        print("gdal_translate not found — trying rasterio/numpy fallback", file=sys.stderr)
        return _fallback_geotiff_to_png(geotiff_path, png_path, target_width)

    # First resample to target_width x target_width with bilinear, output PNG
    cmd = [
        "gdal_translate",
        "-outsize", str(target_width), str(target_width),
        "-of", "PNG",
        "-scale",           # auto-scale to 8-bit (lost below — we override)
        geotiff_path, png_path,
    ]
    # We want a 16-bit PNG for accuracy. Use unscaled 16-bit:
    cmd = [
        "gdal_translate",
        "-outsize", str(target_width), str(target_width),
        "-ot", "UInt16",
        "-of", "PNG",
        geotiff_path, png_path,
    ]
    subprocess.run(cmd, check=True)
    print(f"saved heightmap: {png_path}")


def _fallback_geotiff_to_png(geotiff_path, png_path, target_width=512):
    try:
        import rasterio
        from rasterio.windows import from_bounds
        import numpy as np
    except ImportError as e:
        raise RuntimeError(
            "Need gdal_translate OR rasterio+numpy to convert GeoTIFF. "
            f"Got: {e}"
        )

    lat, lon = CENTER
    cx, cy = latlon_to_meters(lat, lon)
    x_min, x_max = cx - HALF_BOX_M, cx + HALF_BOX_M
    y_min, y_max = cy - HALF_BOX_M, cy + HALF_BOX_M
    lat_min, lon_min = meters_to_latlon(x_min, y_min)
    lat_max, lon_max = meters_to_latlon(x_max, y_max)

    with rasterio.open(geotiff_path) as src:
        win = from_bounds(
            lon_min, lat_min, lon_max, lat_max,
            transform=src.transform,
        )
        win = win.round_offsets(op="floor").round_lengths(op="ceil")
        arr = src.read(1, window=win).astype("float32")
        nodata = src.nodata
        if nodata is not None:
            arr = np.where(arr == nodata, np.nan, arr)
        if np.isnan(arr).any():
            med = np.nanmedian(arr)
            arr = np.where(np.isnan(arr), med, arr)
        lo, hi = np.nanmin(arr), np.nanmax(arr)
        print(f"elevation range (cropped to {HALF_BOX_M*2}m box): {lo:.2f}m to {hi:.2f}m, {arr.shape[1]}x{arr.shape[0]} px")
        # Save as 16-bit PNG. Lo=0, hi=65535. Caller applies a strength in Blender.
        norm = ((arr - lo) / (hi - lo + 1e-9) * 65535).astype("uint16")
        img = Image.fromarray(norm)
        img = img.resize((target_width, target_width), Image.BILINEAR)
        img.save(png_path)
        meta_path = os.path.join(OUT_DIR, "heightmap_meta.txt")
        with open(meta_path, "w") as f:
            f.write(f"min_m={lo:.3f}\nmax_m={hi:.3f}\nrange_m={hi-lo:.3f}\n"
                    f"box_m={HALF_BOX_M*2}\ntarget_px={target_width}\n")
        print(f"saved heightmap: {png_path} (elev range {lo:.2f}-{hi:.2f}m)")


def main():
    lat, lon = CENTER
    cx, cy = latlon_to_meters(lat, lon)

    # Big fetch box for OpenTopography's min-area rule.
    x_min, x_max = cx - OP_HALF_BOX_M, cx + OP_HALF_BOX_M
    y_min, y_max = cy - OP_HALF_BOX_M, cy + OP_HALF_BOX_M
    lat_min, lon_min = meters_to_latlon(x_min, y_min)
    lat_max, lon_max = meters_to_latlon(x_max, y_max)

    geotiff = os.path.join(OUT_DIR, "elevation.tif")
    fetch_dem_geotiff(lat_min, lat_max, lon_min, lon_max, geotiff)
    png = os.path.join(OUT_DIR, "heightmap.png")
    geotiff_to_heightmap_png(geotiff, png, target_width=512)


if __name__ == "__main__":
    main()