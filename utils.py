"""Shared utilities for all scripts and notebooks."""

from pathlib import Path

REPO_ROOT = Path(__file__).parent


def load_config():
    cfg = {}
    with open(REPO_ROOT / "config.txt") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, val = line.partition("=")
            cfg[key.strip()] = val.strip()
    return {
        "YEARS": [int(y) for y in cfg["YEARS"].split(",")],
        "RESOLUTION": float(cfg["RESOLUTION"]),
        "TILE_SIZE_DEG": float(cfg["TILE_SIZE_DEG"]),
        "PIXELS_PER_TILE": int(cfg["PIXELS_PER_TILE"]),
        "TILE_ROWS": int(cfg["TILE_ROWS"]),
        "TILE_COLS": int(cfg["TILE_COLS"]),
        "FILL_VALUE": int(cfg["FILL_VALUE"]),
    }


def load_tile_list():
    """Return GeoDataFrame of land tiles from the committed tile_list.geojson."""
    import geopandas as gpd
    return gpd.read_file(REPO_ROOT / "tile_list.geojson")
