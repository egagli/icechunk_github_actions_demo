"""Generate the GitHub Actions matrix of unprocessed land tiles.

Reads the Icechunk commit history to find already-processed tiles, subtracts
them from the full list of land tiles, and prints the remainder as JSON.

No external status log is maintained — Icechunk commit history is the
single source of truth.

Usage:
    python scripts/generate_tile_matrix.py
    # → prints JSON to stdout, progress to stderr
"""

import json
import os
import re
import sys

import icechunk
from cartopy.feature import LAND

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import TILE_COLS, TILE_ROWS, TILE_SIZE_DEG


def get_storage():
    return icechunk.azure_storage(
        account=os.environ["AZURE_STORAGE_ACCOUNT"],
        container=os.environ["AZURE_CONTAINER"],
        prefix=os.environ["ICECHUNK_PREFIX"],
        sas_token=os.environ["AZURE_STORAGE_SAS_TOKEN"],
    )


def all_land_tiles():
    """Return list of {row, col} dicts for tiles that intersect land."""
    tiles = []
    for row in range(TILE_ROWS):
        for col in range(TILE_COLS):
            lat_min = -90 + row * TILE_SIZE_DEG
            lon_min = -180 + col * TILE_SIZE_DEG
            extent = (lon_min, lon_min + TILE_SIZE_DEG, lat_min, lat_min + TILE_SIZE_DEG)
            if list(LAND.intersecting_geometries(extent)):
                tiles.append({"row": row, "col": col})
    return tiles


def processed_tiles(repo):
    """Parse Icechunk commit messages to find successfully processed tiles."""
    session = repo.readonly_session("main")
    pattern = re.compile(r"tile_(\d+)_(\d+): processed")
    processed = set()
    for commit in session.ancestry():
        m = pattern.match(commit.message)
        if m:
            processed.add((int(m.group(1)), int(m.group(2))))
    return processed


def main():
    storage = get_storage()
    repo = icechunk.Repository.open(storage)

    land = all_land_tiles()
    done = processed_tiles(repo)
    unprocessed = [t for t in land if (t["row"], t["col"]) not in done]

    print(
        f"{len(land)} land tiles total, {len(done)} processed, "
        f"{len(unprocessed)} remaining",
        file=sys.stderr,
    )
    print(json.dumps({"tile": unprocessed}))


if __name__ == "__main__":
    main()
