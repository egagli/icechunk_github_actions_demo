"""Generate the GitHub Actions matrix of unprocessed land tiles.

Two modes:
    --list-batches          Print batch index JSON: {"batch_index": [0, 1, ...]}
    --batch-index N         Print tile JSON for batch N: {"tile": [...]}

Reads tile_list.geojson (pre-committed) and the Icechunk commit history to find
already-processed tiles. No external status log is maintained — Icechunk commit
history is the single source of truth.

Usage:
    python scripts/generate_tile_matrix.py --list-batches
    python scripts/generate_tile_matrix.py --batch-index 0
"""

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import icechunk
from icechunk_github_actions_demo import Config, get_processing_status_gdf

BATCH_SIZE = 256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list-batches", action="store_true",
                       help="Print batch index list as JSON")
    group.add_argument("--batch-index", type=int,
                       help="Print tile list for batch N as JSON")
    args = parser.parse_args()

    config = Config("config/config_v1.txt")
    storage = icechunk.azure_storage(
        account=config.AZURE_STORAGE_ACCOUNT,
        container=config.AZURE_CONTAINER,
        prefix=config.ICECHUNK_PREFIX,
        sas_token=config.AZURE_STORAGE_SAS_TOKEN,
    )
    repo = icechunk.Repository.open(storage)

    status_gdf = get_processing_status_gdf(repo, config.TILE_LIST_PATH, config.YEARS)
    land_count = int((status_gdf["status"] != "ocean").sum())
    done_count = int(status_gdf["status"].isin(["processed", "nodata"]).sum())
    unprocessed = [
        {"row": int(r["row"]), "col": int(r["col"])}
        for _, r in status_gdf.iterrows()
        if r["status"] == "unprocessed"
    ]

    num_batches = math.ceil(len(unprocessed) / BATCH_SIZE) if unprocessed else 0

    print(
        f"{land_count} land tiles total, {done_count} processed/nodata, "
        f"{len(unprocessed)} remaining, {num_batches} batch(es)",
        file=sys.stderr,
    )

    if args.list_batches:
        print(json.dumps({"batch_index": list(range(num_batches))}))
    else:
        start = args.batch_index * BATCH_SIZE
        batch = unprocessed[start : start + BATCH_SIZE]
        print(json.dumps({"tile": batch}))


if __name__ == "__main__":
    main()
