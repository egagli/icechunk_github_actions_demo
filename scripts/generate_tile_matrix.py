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
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import icechunk
from utils import load_tile_list


def processed_tiles(repo):
    """Parse Icechunk commit messages to find successfully processed tiles."""
    pattern = re.compile(r"tile_(\d+)_(\d+): processed")
    processed = set()
    for commit in repo.ancestry(branch="main"):
        m = pattern.match(commit.message)
        if m:
            processed.add((int(m.group(1)), int(m.group(2))))
    return processed


def main():
    storage = icechunk.azure_storage(
        account=os.environ["AZURE_STORAGE_ACCOUNT"],
        container=os.environ["AZURE_CONTAINER"],
        prefix=os.environ["ICECHUNK_PREFIX"],
        sas_token=os.environ["AZURE_STORAGE_SAS_TOKEN"],
    )
    repo = icechunk.Repository.open(storage)

    tile_gdf = load_tile_list()
    land = [{"row": int(r["row"]), "col": int(r["col"])} for _, r in tile_gdf.iterrows()]
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
