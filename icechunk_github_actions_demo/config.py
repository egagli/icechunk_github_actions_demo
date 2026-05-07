"""Dataset configuration, global geobox, and tile utilities.

Usage:
    from icechunk_github_actions_demo import Config, list_processed_tiles
    config = Config("config/config_v1.txt")          # CI: credentials from env vars
    config = Config("config/config_with_secrets_v1.txt")  # local: literal credentials

Credential fields set to "ENV" in the config file are resolved from os.environ.
"""

import os
import re
from functools import cached_property
from pathlib import Path

import geopandas as gpd
import numpy as np
import odc.geo
from odc.geo.geobox import GeoBox

REPO_ROOT = Path(__file__).parent.parent


def geoboxtiles_to_gdf(gbt):
    """Convert odc.geo.geobox.GeoboxTiles to a GeoDataFrame with one polygon per tile."""
    nrows, ncols = gbt.shape.yx
    records = []
    geoms = []
    for irow, icol in np.ndindex(nrows, ncols):
        tile = gbt[irow, icol]
        geoms.append(tile.extent.geom)
        records.append({"row": irow, "col": icol})
    return gpd.GeoDataFrame(
        records,
        geometry=geoms,
        crs=str(gbt.base.crs) if gbt.base.crs is not None else None,
    )


def list_processed_tiles(repo):
    """Return the set of (row, col) tuples already committed to the Icechunk store.

    Parses commit messages matching 'tile_R_C: processed' from the full ancestry
    of the main branch. Icechunk commit history is the single source of truth —
    no external status log is maintained.
    """
    pattern = re.compile(r"tile_(\d+)_(\d+): processed")
    done = set()
    for commit in repo.ancestry(branch="main"):
        m = pattern.match(commit.message)
        if m:
            done.add((int(m.group(1)), int(m.group(2))))
    return done


class Config:
    def __init__(self, config_path):
        raw = {}
        with open(REPO_ROOT / config_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                raw[key] = os.environ[key] if val == "ENV" else val

        self.YEARS = [int(y) for y in raw["YEARS"].split(",")]
        self.RESOLUTION = float(raw["RESOLUTION"])
        self.TILE_SIZE_DEG = float(raw["TILE_SIZE_DEG"])
        self.PIXELS_PER_TILE = int(raw["PIXELS_PER_TILE"])
        self.TILE_ROWS = int(raw["TILE_ROWS"])
        self.TILE_COLS = int(raw["TILE_COLS"])
        self.FILL_VALUE = int(raw["FILL_VALUE"])
        
        self.TILE_LIST_PATH = (REPO_ROOT / raw["TILE_LIST_PATH"])

        self.AZURE_STORAGE_ACCOUNT = raw["AZURE_STORAGE_ACCOUNT"]
        self.AZURE_STORAGE_SAS_TOKEN = raw["AZURE_STORAGE_SAS_TOKEN"]
        self.AZURE_CONTAINER = raw["AZURE_CONTAINER"]
        self.ICECHUNK_PREFIX = raw["ICECHUNK_PREFIX"]

        self.global_geobox = GeoBox.from_bbox(
            (-180, -90, 180, 90), crs="epsg:4326", resolution=self.RESOLUTION
        )
        self._geobox_tiles = odc.geo.GeoboxTiles(
            self.global_geobox, (self.PIXELS_PER_TILE, self.PIXELS_PER_TILE)
        )

    def tile_geobox(self, row, col):
        """Return the GeoBox for one tile — a direct slice of the global geobox.

        Passing this to odc.stac.load guarantees output coordinates are
        bit-for-bit identical to the Zarr store's coordinate arrays.
        """
        return self._geobox_tiles[(row, col)]

    @cached_property
    def global_geobox_tiles_gdf(self):
        """GeoDataFrame of all tiles derived from the global geobox (no land filter)."""
        return geoboxtiles_to_gdf(self._geobox_tiles)
