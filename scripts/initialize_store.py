"""Initialize the empty Icechunk/Zarr v3 store.

Run once before processing any tiles. Writes only metadata and coordinates;
no data chunks are created until tile runners fill them in.
"""

import os
import sys

import dask.array as da
import icechunk
import numpy as np
import xarray as xr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import FILL_VALUE, PIXELS_PER_TILE, RESOLUTION, TILE_COLS, TILE_ROWS, YEARS


def get_storage():
    return icechunk.azure_storage(
        account=os.environ["AZURE_STORAGE_ACCOUNT"],
        container=os.environ["AZURE_CONTAINER"],
        prefix=os.environ["ICECHUNK_PREFIX"],
        sas_token=os.environ["AZURE_STORAGE_SAS_TOKEN"],
    )


def main():
    n_lat = TILE_ROWS * PIXELS_PER_TILE  # 18000
    n_lon = TILE_COLS * PIXELS_PER_TILE  # 36000
    shape = (len(YEARS), n_lat, n_lon)
    chunks = (1, PIXELS_PER_TILE, PIXELS_PER_TILE)

    # Pixel-center coordinates: lats descend from 90, lons ascend from -180
    lats = np.arange(90, -90, -RESOLUTION) - RESOLUTION / 2
    lons = np.arange(-180, 180, RESOLUTION) + RESOLUTION / 2

    var_attrs = {
        "scale_factor": np.float32(0.02),
        "add_offset": np.float32(0.0),
        "_FillValue": FILL_VALUE,
        "valid_range": [7500, 65535],
        "units": "K",
        "grid_mapping": "spatial_ref",
    }

    ds = xr.Dataset(
        {
            "avg_daytime_lst": xr.DataArray(
                da.full(shape, np.uint16(FILL_VALUE), dtype=np.uint16, chunks=chunks),
                dims=["year", "latitude", "longitude"],
                attrs={**var_attrs, "long_name": "Annual mean daytime land surface temperature"},
            ),
            "max_daytime_lst": xr.DataArray(
                da.full(shape, np.uint16(FILL_VALUE), dtype=np.uint16, chunks=chunks),
                dims=["year", "latitude", "longitude"],
                attrs={**var_attrs, "long_name": "Annual maximum daytime land surface temperature"},
            ),
        },
        coords={"year": np.array(YEARS), "latitude": lats, "longitude": lons},
    )
    ds.attrs = {
        "title": "MODIS MOD11A2 Annual Daytime Land Surface Temperature (2020-2022)",
        "source": "MODIS Terra MOD11A2 Version 6.1 via Microsoft Planetary Computer",
        "Conventions": "CF-1.8",
    }

    print(f"Dataset to initialize:\n{ds}\n")

    storage = get_storage()
    print("Creating Icechunk repository...")
    repo = icechunk.Repository.create(storage)
    session = repo.writable_session("main")

    print(f"Writing empty template (shape={shape}, chunks={chunks})...")
    # compute=False: write only metadata/coordinates, not data arrays
    # write_empty_chunks=False: no chunks materialized until runners fill them
    ds.to_zarr(
        session.store,
        mode="w",
        zarr_format=3,
        compute=False,
        write_empty_chunks=False,
        consolidated=False,
    )

    snapshot_id = session.commit("initialize store: empty template, 2020-2022")
    print(f"Done. Snapshot ID: {snapshot_id}")


if __name__ == "__main__":
    main()
