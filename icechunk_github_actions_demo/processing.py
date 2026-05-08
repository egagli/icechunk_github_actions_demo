"""MODIS LST data fetching and quality filtering."""

import logging

import numpy as np
import odc.stac
import planetary_computer
import pystac_client

logger = logging.getLogger(__name__)

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


def fetch_annual_lst(tile_geobox, year, pixels_per_tile):
    """Fetch MODIS MOD11A2 LST for one tile and one year.

    Returns (avg_lst, max_lst) as uint16 DataArrays, or (None, None) if no data.
    The tile_geobox is passed directly to odc.stac.load to ensure output coordinates
    are pixel-aligned with the global Zarr store.
    """
    odc.stac.configure_rio(cloud_defaults=True)
    bbox = tile_geobox.boundingbox

    catalog = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)

    logger.info(f"  [{year}] Searching STAC ({bbox.left:.1f},{bbox.bottom:.1f} → {bbox.right:.1f},{bbox.top:.1f})...")
    items = catalog.search(
        collections=["modis-11A2-061"],
        bbox=[bbox.left, bbox.bottom, bbox.right, bbox.top],
        datetime=f"{year}-01-01/{year}-12-31",
    ).item_collection()

    if not items:
        logger.info(f"  [{year}] No items found, skipping")
        return None, None

    dates = sorted(i.datetime.date() for i in items)
    logger.info(f"  [{year}] Found {len(items)} items ({dates[0]} → {dates[-1]})")

    logger.info(f"  [{year}] Loading {len(items)} granules via odc.stac...")
    ds = odc.stac.load(
        items,
        bands=["LST_Day_1km", "QC_Day"],
        geobox=tile_geobox,
        chunks={"time": 1, "x": pixels_per_tile, "y": pixels_per_tile},
    )

    # QC_Day bits 0-1: 0b00 = good, 0b01 = nominal quality
    good = (ds.QC_Day & 0b11) <= 1
    lst = ds.LST_Day_1km.where(good).where(ds.LST_Day_1km >= 7500)
    lst = lst.compute()

    logger.info(f"  [{year}] Computing annual mean and max over {len(ds.time)} time steps...")
    avg_lst = lst.mean("time").astype(np.uint16)
    max_lst = lst.max("time").astype(np.uint16)
    logger.info(f"  [{year}] Compute complete")
    return avg_lst, max_lst
