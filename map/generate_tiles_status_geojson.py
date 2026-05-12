"""Generate public/tiles-status.geojson from the Icechunk commit history.

Run locally:
    pixi run -e ci python map/generate_tiles_status_geojson.py

Run in CI: see .github/workflows/deploy-map.yml — this script is called
automatically before the Next.js build so the map always reflects the
latest processing status.

Requires AZURE_STORAGE_ACCOUNT, AZURE_STORAGE_SAS_TOKEN, AZURE_CONTAINER,
and ICECHUNK_PREFIX as environment variables (or in a secrets config file).
"""

from pathlib import Path

import icechunk

# Script lives at map/generate_tiles_status_geojson.py — resolve repo root.
REPO_ROOT = Path(__file__).parent.parent
OUTPUT = Path(__file__).parent / "public" / "tiles-status.geojson"


def main():
    from icechunk_github_actions_demo.config import Config, get_processing_status_gdf

    config = Config("config/config_v1.txt")

    storage = icechunk.azure_storage(
        account=config.AZURE_STORAGE_ACCOUNT,
        container=config.AZURE_CONTAINER,
        prefix=config.ICECHUNK_PREFIX,
        sas_token=config.AZURE_STORAGE_SAS_TOKEN,
    )
    repo = icechunk.Repository.open(storage)

    gdf = get_processing_status_gdf(
        repo=repo,
        tile_list_path=config.TILE_LIST_PATH,
        years=config.YEARS,
    )

    # Drop ocean tiles — the map filters on land=true anyway.
    gdf = gdf[gdf["status"] != "ocean"].copy()

    # Keep only columns the map needs.
    keep = ["row", "col", "land", "status", "geometry"]
    gdf = gdf[[c for c in keep if c in gdf.columns]]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(OUTPUT, driver="GeoJSON")
    print(f"Written {len(gdf)} tiles → {OUTPUT}")


if __name__ == "__main__":
    main()
