"""Initialize the empty Icechunk/Zarr v3 store.

Run once before processing any tiles. Writes only metadata and coordinates;
no data chunks are created until tile runners fill them in.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import dask.array as da
import icechunk
import numpy as np
import xarray as xr
from config import Config


def main():
    cfg = Config("config/config_v1.txt")

    n_lat = cfg.TILE_ROWS * cfg.PIXELS_PER_TILE
    n_lon = cfg.TILE_COLS * cfg.PIXELS_PER_TILE
    shape = (len(cfg.YEARS), n_lat, n_lon)
    chunks = (1, cfg.PIXELS_PER_TILE, cfg.PIXELS_PER_TILE)

    lats = np.arange(90, -90, -cfg.RESOLUTION) - cfg.RESOLUTION / 2
    lons = np.arange(-180, 180, cfg.RESOLUTION) + cfg.RESOLUTION / 2

    var_attrs = {
        "scale_factor": np.float32(0.02),
        "add_offset": np.float32(0.0),
        "_FillValue": cfg.FILL_VALUE,
        "valid_range": [7500, 65535],
        "units": "K",
        "grid_mapping": "spatial_ref",
    }

    ds = xr.Dataset(
        {
            "avg_daytime_lst": xr.DataArray(
                da.full(shape, np.uint16(cfg.FILL_VALUE), dtype=np.uint16, chunks=chunks),
                dims=["year", "latitude", "longitude"],
                attrs={**var_attrs, "long_name": "Annual mean daytime land surface temperature"},
            ),
            "max_daytime_lst": xr.DataArray(
                da.full(shape, np.uint16(cfg.FILL_VALUE), dtype=np.uint16, chunks=chunks),
                dims=["year", "latitude", "longitude"],
                attrs={**var_attrs, "long_name": "Annual maximum daytime land surface temperature"},
            ),
        },
        coords={"year": np.array(cfg.YEARS), "latitude": lats, "longitude": lons},
    )
    ds.attrs = {
        "title": "MODIS MOD11A2 Annual Daytime Land Surface Temperature",
        "source": "MODIS Terra MOD11A2 Version 6.1 via Microsoft Planetary Computer",
        "Conventions": "CF-1.8",
    }

    print(f"Dataset to initialize:\n{ds}\n")

    storage = icechunk.azure_storage(
        account=cfg.AZURE_STORAGE_ACCOUNT,
        container=cfg.AZURE_CONTAINER,
        prefix=cfg.ICECHUNK_PREFIX,
        sas_token=cfg.AZURE_STORAGE_SAS_TOKEN,
    )

    print("Creating Icechunk repository...")
    repo = icechunk.Repository.create(storage)
    session = repo.writable_session("main")

    print(f"Writing empty template (shape={shape}, chunks={chunks})...")
    ds.to_zarr(
        session.store,
        mode="w",
        zarr_format=3,
        compute=False,
        write_empty_chunks=False,
        consolidated=False,
    )

    snapshot_id = session.commit("initialize store: empty template")
    print(f"Done. Snapshot ID: {snapshot_id}")


if __name__ == "__main__":
    main()
