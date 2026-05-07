"""MODIS LST data fetching and quality filtering."""

import numpy as np
import odc.stac
import pystac_client

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


def fetch_annual_lst(tile_geobox, year, pixels_per_tile):
    """Fetch MODIS MOD11A2 LST for one tile and one year.

    Returns (avg_lst, max_lst) as uint16 DataArrays, or (None, None) if no data.
    The tile_geobox is passed directly to odc.stac.load to ensure output coordinates
    are pixel-aligned with the global Zarr store.
    """
    bbox = tile_geobox.boundingbox

    catalog = pystac_client.Client.open(STAC_URL)
    items = catalog.search(
        collections=["modis-11A2-061"],
        bbox=[bbox.left, bbox.bottom, bbox.right, bbox.top],
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
