"""Generate the GitHub Actions matrix of unprocessed land tiles.

Reads tile_list.geojson (pre-computed, committed to the repo) and the Icechunk
commit history to find already-processed tiles, then prints the remainder as JSON.

No external status log is maintained — Icechunk commit history is the
single source of truth.

Usage:
    python scripts/generate_tile_matrix.py
    # → prints JSON to stdout, progress to stderr
"""

import json
import sys
from pathlib import Path
import geopandas as gpd

sys.path.insert(0, str(Path(__file__).parent.parent))

import icechunk
from icechunk_github_actions_demo import Config, list_processed_tiles


def main():
    config = Config("config/config_v1.txt")

    storage = icechunk.azure_storage(
        account=config.AZURE_STORAGE_ACCOUNT,
        container=config.AZURE_CONTAINER,
        prefix=config.ICECHUNK_PREFIX,
        sas_token=config.AZURE_STORAGE_SAS_TOKEN,
    )
    repo = icechunk.Repository.open(storage)

    tile_gdf = gpd.read_file(config.TILE_LIST_PATH)
    land = [{"row": int(r["row"]), "col": int(r["col"])} for _, r in tile_gdf.iterrows() if r["land"]]
    done = list_processed_tiles(repo)
    unprocessed = [t for t in land if (t["row"], t["col"]) not in done]

    print(
        f"{len(land)} land tiles total, {len(done)} processed, "
        f"{len(unprocessed)} remaining",
        file=sys.stderr,
    )
    print(json.dumps({"tile": unprocessed}))


if __name__ == "__main__":
    main()
