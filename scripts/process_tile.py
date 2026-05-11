"""Process a single 10°×10° tile and write results to the shared Icechunk store.

Each GitHub Actions runner calls this script for one tile. Results for all
available years are written to the store in a single Icechunk commit.
"""

import argparse
import logging
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import icechunk
import xarray as xr
from icechunk_github_actions_demo import Config
from icechunk_github_actions_demo.processing import fetch_annual_lst

SPECIAL_NOTE_NONE = "None"
SPECIAL_NOTE_NODATA = "No input data found for any year, therefore no output written to tile."

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _coverage(arr, fill_value=0):
    """Return (valid_pixel_count, coverage_pct) for a 2-D uint16 DataArray."""
    valid = int((arr.values > fill_value).sum())
    total = arr.values.size
    return valid, 100.0 * valid / total


def _write_step_summary(tile_row, tile_col, bbox, per_year, snapshot_id, fill_value=0):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        f"## Tile ({tile_row}, {tile_col})",
        f"**Bounds:** lat [{bbox.bottom:.1f}, {bbox.top:.1f}], lon [{bbox.left:.1f}, {bbox.right:.1f}]",
        "",
        "| Year | Valid pixels | Coverage |",
        "| ---- | ----------- | -------- |",
    ]
    for yr, v in sorted(per_year.items()):
        valid, pct = _coverage(v["avg"], fill_value)
        lines.append(f"| {yr} | {valid:,} | {pct:.1f}% |")
    lines += ["", f"**Snapshot:** `{snapshot_id}`"]
    with open(summary_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main(tile_row, tile_col):
    config = Config("config/config_v1.txt")
    tile_geobox = config.tile_geobox(tile_row, tile_col)
    bbox = tile_geobox.boundingbox
    logger.info(
        f"Tile ({tile_row}, {tile_col}): "
        f"lat [{bbox.bottom:.1f}, {bbox.top:.1f}], lon [{bbox.left:.1f}, {bbox.right:.1f}]"
    )

    per_year = {}
    for year in config.YEARS:
        logger.info(f"  [{year}] Starting fetch...")
        avg_lst, max_lst = fetch_annual_lst(tile_geobox, year, config.PIXELS_PER_TILE)
        if avg_lst is None:
            logger.info(f"  [{year}] No data — skipping")
            continue
        valid, pct = _coverage(avg_lst, config.FILL_VALUE)
        logger.info(f"  [{year}] Done — {valid:,} valid pixels ({pct:.1f}% coverage)")
        per_year[year] = {"avg": avg_lst, "max": max_lst}

    stats_parts = [
        f"({yr}: valid_pixels={_coverage(v['avg'], config.FILL_VALUE)[0]}, coverage={_coverage(v['avg'], config.FILL_VALUE)[1]:.1f}%)"
        for yr, v in sorted(per_year.items())
    ]
    stats_str = "[" + ", ".join(stats_parts) + "]"

    if not per_year:
        logger.info("No data found for any year — committing nodata marker.")
        special_note = SPECIAL_NOTE_NODATA
    else:
        special_note = SPECIAL_NOTE_NONE

    lat_start = tile_row * config.PIXELS_PER_TILE
    lon_start = tile_col * config.PIXELS_PER_TILE

    storage = icechunk.azure_storage(
        account=config.AZURE_STORAGE_ACCOUNT,
        container=config.AZURE_CONTAINER,
        prefix=config.ICECHUNK_PREFIX,
        sas_token=config.AZURE_STORAGE_SAS_TOKEN,
    )
    repo = icechunk.Repository.open(storage)

    logger.info(f"Writing {len(per_year)} year(s) to store...")
    while True:
        try:
            session = repo.writable_session("main")

            for yr, v in per_year.items():
                year_idx = config.YEARS.index(yr)
                region = {
                    "year": slice(year_idx, year_idx + 1),
                    "latitude": slice(lat_start, lat_start + config.PIXELS_PER_TILE),
                    "longitude": slice(lon_start, lon_start + config.PIXELS_PER_TILE),
                }
                year_ds = xr.Dataset(
                    {
                        "avg_daytime_lst": v["avg"].expand_dims(year=[yr]),
                        "max_daytime_lst": v["max"].expand_dims(year=[yr]),
                    }
                ).drop_vars("spatial_ref", errors="ignore").chunk({"year": 1, "latitude": config.PIXELS_PER_TILE, "longitude": config.PIXELS_PER_TILE})
                logger.info(f"  Writing year {yr} (region lat {lat_start}:{lat_start + config.PIXELS_PER_TILE}, lon {lon_start}:{lon_start + config.PIXELS_PER_TILE})...")
                year_ds.to_zarr(
                    session.store, region=region, zarr_format=3, consolidated=False
                )

            snapshot_id = session.commit(
                f"Tile(row={tile_row}, col={tile_col}) processed. Stats: {stats_str} Special note: {special_note}",
                rebase_with=icechunk.ConflictDetector(),
            )
            logger.info(f"Committed. Snapshot: {snapshot_id}")
            _write_step_summary(tile_row, tile_col, bbox, per_year, snapshot_id, config.FILL_VALUE)
            break

        except Exception as exc:
            delay = random.uniform(3, 10)
            logger.warning(f"Conflict detected, retrying in {delay:.1f}s: {exc}")
            time.sleep(delay)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tile-row", type=int, required=True)
    parser.add_argument("--tile-col", type=int, required=True)
    args = parser.parse_args()
    main(args.tile_row, args.tile_col)
