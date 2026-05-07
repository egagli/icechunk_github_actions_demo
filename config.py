"""Dataset configuration and derived spatial objects.

Usage:
    from config import Config
    cfg = Config("config/config_v1.txt")          # CI: reads credentials from env vars
    cfg = Config("config/config_with_secrets_v1.txt")  # local: reads credentials from file

Credential fields set to "ENV" in the config file are resolved from os.environ.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent


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

        self.AZURE_STORAGE_ACCOUNT = raw["AZURE_STORAGE_ACCOUNT"]
        self.AZURE_STORAGE_SAS_TOKEN = raw["AZURE_STORAGE_SAS_TOKEN"]
        self.AZURE_CONTAINER = raw["AZURE_CONTAINER"]
        self.ICECHUNK_PREFIX = raw["ICECHUNK_PREFIX"]

        import odc.geo
        from odc.geo.geobox import GeoBox

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
