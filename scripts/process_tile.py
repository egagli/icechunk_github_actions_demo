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
import numpy as np
import odc.stac
import pystac_client
import xarray as xr
from config import Config


def fetch_annual_lst(catalog, tile_geobox, lat_min, lat_max, lon_min, lon_max, year, pixels_per_tile):
    items = catalog.search(
        collections=["modis-11A2-061"],
        bbox=[lon_min, lat_min, lon_max, lat_max],
        datetime=f"{year}-01-01/{year}-12-31",
    ).item_collection()

    if not items:
        return None, None

    ds = odc.stac.load(
        items,
        bands=["LST_Day_1km", "QC_Day"],
        geobox=tile_geobox,
        chunks={"time": 1, "x": pixels_per_tile, "y": pixels_per_tile},
    )

    # QC_Day bits 0-1: 0b00 = good, 0b01 = nominal quality
    good = (ds.QC_Day & 0b11) <= 1
    lst = ds.LST_Day_1km.where(good).where(ds.LST_Day_1km >= 7500)

    avg_lst = lst.mean("time").compute().astype(np.uint16)
    max_lst = lst.max("time").compute().astype(np.uint16)
    return avg_lst, max_lst


def main(tile_row, tile_col):
    cfg = Config("config/config_v1.txt")

    # tile_geobox is a direct slice of the global geobox, guaranteeing
    # odc.stac.load output coordinates match the Zarr store exactly.
    tile_geobox = cfg.tile_geobox(tile_row, tile_col)
    bbox = tile_geobox.boundingbox
    lat_min, lat_max = bbox.bottom, bbox.top
    lon_min, lon_max = bbox.left, bbox.right

    print(
        f"Tile ({tile_row}, {tile_col}): "
        f"lat [{lat_min:.1f}, {lat_max:.1f}], lon [{lon_min:.1f}, {lon_max:.1f}]"
    )

    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1"
    )

    per_year = {}
    for year in cfg.YEARS:
        print(f"  {year}: fetching...")
        avg_lst, max_lst = fetch_annual_lst(
            catalog, tile_geobox, lat_min, lat_max, lon_min, lon_max, year, cfg.PIXELS_PER_TILE
        )
        if avg_lst is None:
            print(f"  {year}: no data, skipping")
            continue
        per_year[year] = {"avg": avg_lst, "max": max_lst}
        print(f"  {year}: done")

    if not per_year:
        print("No data found for any year — skipping.")
        sys.exit(0)

    lat_start = tile_row * cfg.PIXELS_PER_TILE
    lon_start = tile_col * cfg.PIXELS_PER_TILE

    storage = icechunk.azure_storage(
        account=cfg.AZURE_STORAGE_ACCOUNT,
        container=cfg.AZURE_CONTAINER,
        prefix=cfg.ICECHUNK_PREFIX,
        sas_token=cfg.AZURE_STORAGE_SAS_TOKEN,
    )
    repo = icechunk.Repository.open(storage)

    print(f"Writing {len(per_year)} year(s) to store...")
    while True:
        try:
            session = repo.writable_session("main")

            for yr, v in per_year.items():
                year_idx = cfg.YEARS.index(yr)
                region = {
                    "year": slice(year_idx, year_idx + 1),
                    "latitude": slice(lat_start, lat_start + cfg.PIXELS_PER_TILE),
                    "longitude": slice(lon_start, lon_start + cfg.PIXELS_PER_TILE),
                }
                year_ds = xr.Dataset(
                    {
                        "avg_daytime_lst": v["avg"].expand_dims(year=[yr]),
                        "max_daytime_lst": v["max"].expand_dims(year=[yr]),
                    }
                ).chunk({"year": 1, "latitude": cfg.PIXELS_PER_TILE, "longitude": cfg.PIXELS_PER_TILE})

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
