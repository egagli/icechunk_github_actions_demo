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

import sys

import icechunk

# Script lives at map/generate_tiles_status_geojson.py — resolve repo root.
REPO_ROOT = Path(__file__).parent.parent
OUTPUT = Path(__file__).parent / "public" / "tiles-status.geojson"

# The icechunk_github_actions_demo package has no pyproject.toml / setup.py;
# make it importable by putting the repo root on sys.path.
sys.path.insert(0, str(REPO_ROOT))


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

    # Keep all tiles (including ocean) and all columns so the map can display
    # the full per-tile stats in the info panel.

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(OUTPUT, driver="GeoJSON")
    print(f"Written {len(gdf)} tiles → {OUTPUT}")


if __name__ == "__main__":
    main()
