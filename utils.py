"""Shared utilities for all scripts and notebooks."""

import json
import os
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
    """Return list of {row, col} dicts from the committed tile_list.json."""
    with open(REPO_ROOT / "tile_list.json") as f:
        return json.load(f)


def get_storage():
    import icechunk
    return icechunk.azure_storage(
        account=os.environ["AZURE_STORAGE_ACCOUNT"],
        container=os.environ["AZURE_CONTAINER"],
        prefix=os.environ["ICECHUNK_PREFIX"],
        sas_token=os.environ["AZURE_STORAGE_SAS_TOKEN"],
    )
