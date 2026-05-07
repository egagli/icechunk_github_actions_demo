"""Process a single 10°×10° tile and write results to the shared Icechunk store.

Each GitHub Actions runner calls this script for one tile. Results for all
available years are written to the store in a single Icechunk commit.
"""

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import icechunk
import xarray as xr
from icechunk_github_actions_demo import Config
from icechunk_github_actions_demo.processing import fetch_annual_lst


def main(tile_row, tile_col):
    config = Config("config/config_v1.txt")

    tile_geobox = config.tile_geobox(tile_row, tile_col)
    bbox = tile_geobox.boundingbox
    print(
        f"Tile ({tile_row}, {tile_col}): "
        f"lat [{bbox.bottom:.1f}, {bbox.top:.1f}], lon [{bbox.left:.1f}, {bbox.right:.1f}]"
    )

    per_year = {}
    for year in config.YEARS:
        print(f"  {year}: fetching...")
        avg_lst, max_lst = fetch_annual_lst(tile_geobox, year, config.PIXELS_PER_TILE)
        if avg_lst is None:
            print(f"  {year}: no data, skipping")
            continue
        per_year[year] = {"avg": avg_lst, "max": max_lst}
        print(f"  {year}: done")

    if not per_year:
        print("No data found for any year — skipping.")
        sys.exit(0)

    lat_start = tile_row * config.PIXELS_PER_TILE
    lon_start = tile_col * config.PIXELS_PER_TILE

    storage = icechunk.azure_storage(
        account=config.AZURE_STORAGE_ACCOUNT,
        container=config.AZURE_CONTAINER,
        prefix=config.ICECHUNK_PREFIX,
        sas_token=config.AZURE_STORAGE_SAS_TOKEN,
    )
    repo = icechunk.Repository.open(storage)

    print(f"Writing {len(per_year)} year(s) to store...")
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
                ).chunk({"year": 1, "latitude": config.PIXELS_PER_TILE, "longitude": config.PIXELS_PER_TILE})

                year_ds.to_zarr(
                    session.store, region=region, zarr_format=3, consolidated=False
                )

            snapshot_id = session.commit(
                f"tile_{tile_row}_{tile_col}: processed",
                rebase_with=icechunk.ConflictDetector(),
            )
            print(f"Committed. Snapshot: {snapshot_id}")
            break

        except Exception as exc:
            delay = random.uniform(3, 10)
            print(f"Conflict detected, retrying in {delay:.1f}s: {exc}")
            time.sleep(delay)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tile-row", type=int, required=True)
    parser.add_argument("--tile-col", type=int, required=True)
    args = parser.parse_args()
    main(args.tile_row, args.tile_col)
