"""Shared utilities for all scripts and notebooks."""

from pathlib import Path

REPO_ROOT = Path(__file__).parent


def load_tile_list():
    """Return GeoDataFrame of land tiles (land=True) from the committed tile_list.geojson."""
    import geopandas as gpd

    gdf = gpd.read_file(REPO_ROOT / "tile_list.geojson")
    return gdf[gdf["land"]].reset_index(drop=True)
