"""MODIS LST data fetching and quality filtering."""

import logging

import numpy as np
import odc.geo.xr  # registers .odc accessor needed for reproject workaround
import odc.stac
import planetary_computer
import pystac_client

logger = logging.getLogger(__name__)

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


def _is_antimeridian_tile(bbox):
    """True for tiles whose edge touches ±180°.

    odc.geo._relative_rois miscomputes pixel overlap near the antimeridian
    (odc-geo#176, odc-stac#172 — unfixed as of 2025-05). Tiles in column 0
    (left edge at −180°) and column 35 (right edge at +180°) are affected.
    """
    return bbox.right >= 179.999 or bbox.left <= -179.999


def _utm_crs_for_tile(bbox):
    """Return a UTM CRS whose central meridian keeps ±180° away from any edge.

    col 35 (lon 170-180°E): UTM Zone 60N/S centred at 177°E
    col  0 (lon -180–-170°): UTM Zone 1N/S  centred at 177°W
    N/S variant chosen by tile centre latitude so coordinates stay in the
    standard positive-northing range for that hemisphere.
    """
    south = (bbox.top + bbox.bottom) / 2 < 0
    if bbox.right >= 179.999:
        return "EPSG:32760" if south else "EPSG:32660"
    return "EPSG:32701" if south else "EPSG:32601"


def fetch_annual_lst(tile_geobox, year, pixels_per_tile):
    """Fetch MODIS MOD11A2 LST for one tile and one year.

    Returns (avg_lst, max_lst) as uint16 DataArrays, or (None, None, 0) if no
    data. For tiles adjacent to the antimeridian, bypasses the buggy geobox
    code path by loading without a geobox then reprojecting.
    """
    odc.stac.configure_rio(cloud_defaults=True)
    bbox = tile_geobox.boundingbox

    catalog = pystac_client.Client.open(
        STAC_URL, modifier=planetary_computer.sign_inplace
    )

    logger.info(
        f"  [{year}] Searching STAC "
        f"({bbox.left:.1f},{bbox.bottom:.1f} → "
        f"{bbox.right:.1f},{bbox.top:.1f})..."
    )
    items = catalog.search(
        collections=["modis-11A2-061"],
        bbox=[bbox.left, bbox.bottom, bbox.right, bbox.top],
        datetime=f"{year}-01-01/{year}-12-31",
    ).item_collection()

    if not items:
        logger.info(f"  [{year}] No items found, skipping")
        return None, None, 0

    granule_count = len(items)
    dates = sorted(
        (i.datetime or i.common_metadata.start_datetime).date() for i in items
    )
    logger.info(
        f"  [{year}] Found {granule_count} items "
        f"({dates[0]} → {dates[-1]})"
    )

    logger.info(f"  [{year}] Loading {len(items)} granules via odc.stac...")
    if _is_antimeridian_tile(bbox):
        # Workaround for odc-geo#176: _relative_rois miscomputes pixel overlap
        # near ±180° during sinusoidal→EPSG:4326 transform, dropping granules.
        # Load into UTM (antimeridian away from tile centre), apply QC+scale,
        # compute the full time stack, then reproject only the 2D mean/max to
        # the EPSG:4326 grid.  Reprojecting the full dask time-stack triggers a
        # separate bug in dask_rio_reproject (GeoboxTiles.grid_intersect fails
        # to close a LinearRing for large UTM footprints).
        utm_crs = _utm_crs_for_tile(bbox)
        logger.info(
            f"  [{year}] Antimeridian tile — loading via {utm_crs}"
        )
        ds = odc.stac.load(
            items,
            bands=["LST_Day_1km", "QC_Day"],
            crs=utm_crs,
            resolution=1000,  # native MODIS ~1 km in metres
            chunks={"time": 1},
        )
        good = (ds.QC_Day & 0b11) <= 1
        lst = ds.LST_Day_1km.where(good).where(ds.LST_Day_1km >= 7500) * 0.02
        lst = lst.compute()
        logger.info(
            f"  [{year}] Computing annual mean and max "
            f"over {len(ds.time)} time steps..."
        )
        avg_lst = lst.mean("time").odc.reproject(
            tile_geobox, resampling="nearest"
        )
        max_lst = lst.max("time").odc.reproject(
            tile_geobox, resampling="nearest"
        )
        # Force exact pixel coords and normalize dim names to longitude/latitude,
        # matching what odc.stac.load produces for EPSG:4326 geoboxes on the
        # regular (non-antimeridian) path and what the Zarr store expects.
        ny, nx = tile_geobox.shape.yx
        t = tile_geobox.affine
        x_name = "longitude" if "longitude" in avg_lst.coords else "x"
        y_name = "latitude" if "latitude" in avg_lst.coords else "y"
        coord_patch = {
            x_name: (x_name, t.c + t.a * (np.arange(nx) + 0.5)),
            y_name: (y_name, t.f + t.e * (np.arange(ny) + 0.5)),
        }
        avg_lst = avg_lst.assign_coords(coord_patch)
        max_lst = max_lst.assign_coords(coord_patch)
        if x_name == "x":  # normalize to longitude/latitude to match regular path
            avg_lst = avg_lst.rename({"x": "longitude", "y": "latitude"})
            max_lst = max_lst.rename({"x": "longitude", "y": "latitude"})
        logger.info(f"  [{year}] Compute complete")
        return avg_lst, max_lst, granule_count

    ds = odc.stac.load(
        items,
        bands=["LST_Day_1km", "QC_Day"],
        geobox=tile_geobox,
        chunks={"time": 1, "x": pixels_per_tile, "y": pixels_per_tile},
    )

    # QC_Day bits 0-1: 0b00 = good, 0b01 = nominal quality
    good = (ds.QC_Day & 0b11) <= 1
    lst = ds.LST_Day_1km.where(good).where(ds.LST_Day_1km >= 7500) * 0.02
    lst = lst.compute()

    logger.info(
        f"  [{year}] Computing annual mean and max "
        f"over {len(ds.time)} time steps..."
    )
    avg_lst = lst.mean("time")
    max_lst = lst.max("time")
    logger.info(f"  [{year}] Compute complete")
    return avg_lst, max_lst, granule_count
