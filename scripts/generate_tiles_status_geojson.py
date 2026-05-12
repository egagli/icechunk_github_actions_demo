"""Generate map/public/tiles-status.geojson with per-tile processing status.

Run from the repo root:
    pixi run python scripts/generate_tiles_status_geojson.py

Requires: icechunk, geopandas, and a valid config file with credentials.

The output GeoJSON is loaded by the web map (map/components/Map.tsx) to show
a toggleable processing-status overlay.  Status values:
    "processed"   — data written to the Icechunk store
    "nodata"      — land tile committed but no MODIS input found
    "unprocessed" — land tile not yet committed
    "ocean"       — filtered out (not written to output)
"""

import json
from pathlib import Path

import icechunk

REPO_ROOT = Path(__file__).parent.parent
OUTPUT = REPO_ROOT / "map" / "public" / "tiles-status.geojson"


def main():
    from icechunk_github_actions_demo.config import Config, get_processing_status_gdf

    config = Config("config/config_with_secrets_v1.txt")

    storage = icechunk.StorageConfig.s3_from_env(
        bucket=config.ICECHUNK_BUCKET,
        prefix=config.ICECHUNK_PREFIX,
        region=config.ICECHUNK_REGION,
    )
    repo = icechunk.Repository.open_existing(storage=storage)

    gdf = get_processing_status_gdf(
        repo=repo,
        tile_list_path=config.TILE_LIST_PATH,
        years=config.YEARS,
    )

    # Drop ocean tiles to keep file size down; the map filters on land=true anyway.
    gdf = gdf[gdf["status"] != "ocean"].copy()

    # Keep only columns needed by the map.
    keep = ["row", "col", "land", "status", "geometry"]
    gdf = gdf[[c for c in keep if c in gdf.columns]]

    gdf.to_file(OUTPUT, driver="GeoJSON")
    print(f"Written {len(gdf)} tiles to {OUTPUT}")


if __name__ == "__main__":
    main()
