"""Dataset configuration, global geobox, and tile utilities.

Usage:
    from icechunk_github_actions_demo import Config, get_processing_status_gdf
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

SPECIAL_NOTE_NONE = "None"
SPECIAL_NOTE_NODATA = "No input data found for any year, therefore no output written to tile."

# New-format: Tile(row=R, col=C) processed. Stats: [...] Special note: ...
_NEW_MSG_RE = re.compile(
    r"Tile\(row=(\d+), col=(\d+)\) processed\. Stats: \[([^\]]*)\] Special note: (.+)"
)
# Per-year stat entry inside the Stats list
_STAT_RE = re.compile(r"(\d{4}): input_granules=(\d+), output_valid_pixels=(\d+), coverage=([\d.]+)%")
# Legacy format: tile_R_C: processed
_OLD_MSG_RE = re.compile(r"tile_(\d+)_(\d+): processed")


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


def get_processing_status_gdf(repo, tile_list_path, years):
    """Return a GeoDataFrame of all tiles with processing status and per-year pixel counts.

    Status values:
        "processed"   — land tile, data written to store
        "nodata"      — land tile, no MODIS input found, commit made but no data written
        "unprocessed" — land tile, no commit found yet
        "ocean"       — non-land tile

    Per-year columns ``{year}_output_valid_pixels`` (int or NaN) are added for each year in
    ``years``. Legacy commits (old format) are treated as "processed" with NaN stats.
    """
    tile_gdf = gpd.read_file(tile_list_path).copy()

    # Walk commit history once and build a dict keyed by (row, col)
    commit_info = {}
    for commit in repo.ancestry(branch="main"):
        msg = commit.message
        m = _NEW_MSG_RE.match(msg)
        if m:
            row, col = int(m.group(1)), int(m.group(2))
            special_note = m.group(4).strip()
            year_stats = {
                int(sm.group(1)): {
                    "input_granules": int(sm.group(2)),
                    "output_valid_pixels": int(sm.group(3)),
                    "coverage": float(sm.group(4)),
                }
                for sm in _STAT_RE.finditer(m.group(3))
            }
            commit_info[(row, col)] = {"special_note": special_note, "year_stats": year_stats}
            continue
        m = _OLD_MSG_RE.match(msg)
        if m:
            row, col = int(m.group(1)), int(m.group(2))
            # Legacy commit: treat as processed, no per-year stats available
            commit_info.setdefault((row, col), {"special_note": SPECIAL_NOTE_NONE, "year_stats": {}})

    def _status(r):
        key = (int(r["row"]), int(r["col"]))
        if not r["land"]:
            return "ocean"
        if key not in commit_info:
            return "unprocessed"
        if commit_info[key]["special_note"] == SPECIAL_NOTE_NODATA:
            return "nodata"
        return "processed"

    tile_gdf["status"] = tile_gdf.apply(_status, axis=1)

    for yr in years:
        def _output_valid_pixels(r, yr=yr):
            key = (int(r["row"]), int(r["col"]))
            info = commit_info.get(key)
            if info is None:
                return float("nan")
            return info["year_stats"].get(yr, {}).get("output_valid_pixels", float("nan"))

        def _input_granules(r, yr=yr):
            key = (int(r["row"]), int(r["col"]))
            info = commit_info.get(key)
            if info is None:
                return float("nan")
            return info["year_stats"].get(yr, {}).get("input_granules", float("nan"))

        tile_gdf[f"{yr}_output_valid_pixels"] = tile_gdf.apply(_output_valid_pixels, axis=1)
        tile_gdf[f"{yr}_input_granules"] = tile_gdf.apply(_input_granules, axis=1)

    return tile_gdf


def list_processed_tiles(repo):
    """Return the set of (row, col) tuples already committed to the Icechunk store.

    Backward-compat wrapper around get_processing_status_gdf. Prefer using
    get_processing_status_gdf directly for richer status information.
    """
    done = set()
    for commit in repo.ancestry(branch="main"):
        m = _NEW_MSG_RE.match(commit.message) or _OLD_MSG_RE.match(commit.message)
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
