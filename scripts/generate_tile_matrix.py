"""Generate the GitHub Actions matrix of unprocessed land tiles.

Reads tile_list.json (pre-computed, committed to the repo) and the Icechunk
commit history to find already-processed tiles, then prints the remainder as JSON.

No external status log is maintained — Icechunk commit history is the
single source of truth.

Usage:
    python scripts/generate_tile_matrix.py
    # → prints JSON to stdout, progress to stderr
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import icechunk
from utils import get_storage, load_tile_list


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
    storage = get_storage()
    repo = icechunk.Repository.open(storage)

    land = load_tile_list()
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
