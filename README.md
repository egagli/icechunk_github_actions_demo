# icechunk-github-actions-demo

**Author:** Eric Gagliano (egagli@uw.edu) and assisted by claude code  
**Last updated:** May 11th, 2026  

---  

This repository demonstrates how to build a **global-scale raster dataset** using
[GitHub Actions](https://docs.github.com/en/actions) as free, massively parallel compute and
[Icechunk](https://icechunk.io) as a versioned Zarr v3 store. The key insight: Icechunk's
ACID commit model with `ConflictDetector` allows hundreds of independent runners to write
to the same store concurrently — without any external coordinator, lock file, or queue.
Each GitHub Actions runner processes one 10°×10° spatial tile, fetches data from
[Planetary Computer](https://planetarycomputer.microsoft.com), computes annual statistics,
and commits its results; concurrent writes to non-overlapping tile regions are automatically
rebased by Icechunk and never conflict.

The output dataset is annual mean and maximum MODIS daytime land surface temperature
([MOD11A2 v6.1](https://lpdaac.usgs.gov/products/mod11a2v061/)) for 2020–2022, stored
globally at 0.01° (~1 km) in EPSG:4326 — an 18,000 × 36,000 pixel grid. Processing
250,992 MODIS granules (752.98 GB of input data) across 376 land tiles took ~40 minutes
of GitHub Actions time and produced a 1.17 GB Zarr store containing annual summaries.
The GitHub Actions patterns here draw from the
[SciPy 2024 GitHub Actions for Science tutorial](https://scipy2024-githubactionstutorial.readthedocs.io/en/latest/intro.html)
([repo](https://github.com/uwescience/SciPy2024-GitHubActionsTutorial)).

The finished dataset powers an [interactive map](https://egagli.github.io/icechunk_github_actions_demo/)
built with [zarr-layer](https://github.com/carbonplan/zarr-layer) (CarbonPlan's library for
rendering Zarr data as map tiles), Next.js, and deployed automatically to GitHub Pages via
`deploy-map.yml`. The map shows both tile processing status and the actual LST values
rendered directly from the Zarr store. Source lives in [`map/`](map/).

<img width="1613" height="994" alt="image" src="https://github.com/user-attachments/assets/f0d43fa1-adb5-4703-bd9e-692066737830" />   

Check out [the interactive map](https://egagli.github.io/icechunk_github_actions_demo/)! 

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                    Azure Blob Storage                        │
│              Icechunk store (Zarr v3)                        │
│   avg_daytime_lst[year, latitude, longitude]  float32        │
│   max_daytime_lst[year, latitude, longitude]  float32        │
│   shape: (3, 18000, 36000)  chunks: (1, 1000, 1000)         │
└─────────────────────────────────────────────────────────────┘
         ↑ write (region)      ↑ read (commit history)
┌────────┴──────┐   ┌──────────┴───────────┐
│ process_tile  │   │ generate_tile_matrix  │
│ (one per job) │   │ (one job, runs first) │
└───────────────┘   └──────────────────────┘
         GitHub Actions matrix (one runner per tile)
```

**Typical workflow:**

1. Run notebook `01_initialize_and_setup.ipynb` once — creates the empty Icechunk store
2. Run `Process All Tiles` — queries commit history, dispatches one job per
   unprocessed land tile, each writes its region and commits
3. Re-run `Process All Tiles` at any time — already-processed tiles are
   automatically skipped; only failures or new tiles are re-processed

---

## How It Works

### Step 1: Initialize the store (notebook `01_initialize_and_setup.ipynb`)

Run this notebook once before any tile processing. It does two things:

**1a. Build `tile_list.geojson`** — the `Config` class constructs a single
[`odc.geo.GeoBox`](https://odc-geo.readthedocs.io/en/latest/) for the global
0.01° grid and a `GeoboxTiles` object that subdivides it into 18×36 tiles of
1000×1000 pixels each. Tile geometries are derived directly from this same
`GeoboxTiles` object (via `config.global_geobox_tiles_gdf`), so the tile
footprints are provably consistent with the store grid — no separate coordinate
computation is needed. Each tile is then tested against Natural Earth land
polygons to populate the `land` boolean. This geobox-first tile derivation
approach is inspired by
[earthmover's serverless-datacube-demo](https://github.com/earth-mover/serverless-datacube-demo).
Commit `tile_list.geojson`; CI reads it directly without recomputing it.

**1b. Create the empty store** — an xarray Dataset is constructed with the
full output shape backed by `dask.array.full` (never materialized). Coordinates
use cell-center offsets (±½ pixel) so they match the values `odc.stac.load`
produces when given the same geobox to each runner:

```python
shape  = (len(config.YEARS), 18000, 36000)   # years × lat × lon
chunks = (1, 1000, 1000)

# Cell-center coordinates: offset by half a pixel from the grid edges
lats = np.arange(90,  -90, -config.RESOLUTION) - config.RESOLUTION / 2
lons = np.arange(-180, 180,  config.RESOLUTION) + config.RESOLUTION / 2

var_attrs = {
    "scale_factor": np.float32(0.02),   # raw uint16 × 0.02 → Kelvin
    "_FillValue": 0,
    "valid_range": [7500, 65535],
    "units": "K",
    "grid_mapping": "spatial_ref",
}

ds = xr.Dataset(
    {
        "avg_daytime_lst": xr.DataArray(
            da.full(shape, np.uint16(0), dtype=np.uint16, chunks=chunks),
            dims=["year", "latitude", "longitude"],
            attrs={**var_attrs, "long_name": "Annual mean daytime land surface temperature"},
        ),
        "max_daytime_lst": xr.DataArray(
            da.full(shape, np.uint16(0), dtype=np.uint16, chunks=chunks),
            dims=["year", "latitude", "longitude"],
            attrs={**var_attrs, "long_name": "Annual maximum daytime land surface temperature"},
        ),
    },
    coords={"year": np.array(config.YEARS), "latitude": lats, "longitude": lons},
    attrs={"Conventions": "CF-1.8", "title": "MODIS MOD11A2 Annual Daytime LST", ...},
)

repo = icechunk.Repository.create(storage)
session = repo.writable_session("main")
ds.to_zarr(session.store, mode="w", zarr_format=3,
           compute=False, write_empty_chunks=False, consolidated=False)
session.commit("initialize store: empty template")
```

`compute=False` skips materializing the dask arrays; `write_empty_chunks=False`
skips writing any chunk data. The result is a fully-described Zarr v3 store
containing only metadata (`.zarray`, coordinate arrays, CF attributes) — roughly
a few MB on disk even though the declared shape is 8 GB. Runners fill in chunks
as they process tiles.

### Step 2: Generate the tile matrix (`scripts/generate_tile_matrix.py`)

The script determines which tiles need processing by calling
`get_processing_status_gdf(repo, tile_list_path, years)`, which:

1. Reads `tile_list.geojson` to get all tile geometries and their `land` boolean
2. Walks the Icechunk commit history (the single source of truth — no separate
   status log) and parses commit messages of the form:

   ```text
   Tile(row=R, col=C) processed. Stats: [(2020: input_granules=G, output_valid_pixels=N, coverage=P%), ...] Special note: <note>
   ```

3. Returns a GeoDataFrame with a `status` column (`"processed"`, `"nodata"`,
   `"unprocessed"`, `"ocean"`) and per-year `{year}_output_valid_pixels` columns

Only tiles with `status == "unprocessed"` are dispatched. Tiles where no MODIS
input exists for any year (e.g. high-latitude ocean tiles classified as land by
Natural Earth) are committed with `Special note: No input data found for any year,
therefore no output written to tile.` and get `status == "nodata"` — they are
permanently skipped on subsequent runs.

`get_processing_status_gdf` is provided by the `icechunk_github_actions_demo`
package and reused by notebook `02_processing_status.ipynb`. It also handles
legacy commits in the older `tile_R_C: processed` format for backward compatibility.

The script has two modes:

```python
# --list-batches: outputs {"batch_index": [0, 1, ...]} for process_all_tiles.yml
# --batch-index N: outputs {"tile": [...]} for the Nth batch of ≤256 tiles
```

The workflow uses a **batches-of-batches** pattern to stay under the 256-job matrix limit:

```yaml
# process_all_tiles.yml
generate-batches:   # → {"batch_index": [0, 1]}
process-batches:    # matrix over batch indices → calls process_tile_batch.yml per batch

# process_tile_batch.yml (reusable workflow_call)
generate-matrix:    # → {"tile": [...]} for one batch
process-tiles:      # matrix over tiles in that batch
```

### Step 3: Process each tile (`scripts/process_tile.py`)

Each runner fetches MODIS LST from [Planetary Computer](https://planetarycomputer.microsoft.com/dataset/modis-11A2-061),
computes annual statistics, and writes to the store.

**Data fetching**: `fetch_annual_lst` from `icechunk_github_actions_demo.processing`
accepts the tile's `GeoBox` directly. The bounding box for the STAC search is
derived from the geobox, and the same geobox is passed to `odc.stac.load` — this
guarantees output pixel coordinates are bit-for-bit slices of the global store grid.

```python
from icechunk_github_actions_demo.processing import fetch_annual_lst

tile_geobox = config.tile_geobox(tile_row, tile_col)
avg_lst, max_lst, granule_count = fetch_annual_lst(tile_geobox, year, config.PIXELS_PER_TILE)
```

Inside `fetch_annual_lst`, quality filtering and the MODIS scale factor are applied
during fetch — values are returned in Kelvin (float), not raw uint16:

```python
bbox = tile_geobox.boundingbox
items = catalog.search(
    collections=["modis-11A2-061"],
    bbox=[bbox.left, bbox.bottom, bbox.right, bbox.top],
    datetime=f"{year}-01-01/{year}-12-31",
).item_collection()

ds = odc.stac.load(items, bands=["LST_Day_1km", "QC_Day"], geobox=tile_geobox, ...)
# QC_Day bits 0-1: 0b00 = good, 0b01 = nominal quality
good = (ds.QC_Day & 0b11) <= 1
lst = ds.LST_Day_1km.where(good).where(ds.LST_Day_1km >= 7500) * 0.02  # → Kelvin
lst = lst.compute()
avg_lst = lst.mean("time")
max_lst = lst.max("time")
```

**Writing**: each year is written to its integer-indexed region in the store.
All year writes accumulate in the same Icechunk session before a single commit.

```python
while True:
    try:
        session = repo.writable_session("main")  # fresh session on each attempt

        for yr, v in per_year.items():
            year_idx = config.YEARS.index(yr)
            region = {
                "year":      slice(year_idx, year_idx + 1),
                "latitude":  slice(lat_start, lat_start + config.PIXELS_PER_TILE),
                "longitude": slice(lon_start, lon_start + config.PIXELS_PER_TILE),
            }
            year_ds.to_zarr(session.store, region=region, zarr_format=3, ...)

        session.commit(
            f"Tile(row={tile_row}, col={tile_col}) processed. Stats: {stats_str} Special note: {special_note}",
            rebase_with=icechunk.ConflictDetector(),
            allow_empty=special_note == SPECIAL_NOTE_NODATA,  # no-data tiles write nothing
        )
        break

    except Exception as exc:
        time.sleep(random.uniform(3, 10))  # retry on rare timing conflict
```

`ConflictDetector` automatically rebases the commit on top of any concurrent
commits. Because every tile writes to a spatially disjoint region, there are
never real data conflicts — only commit timing collisions, which always resolve.
This optimistic-concurrency retry pattern is described in
[CarbonPlan's OCR pipeline post](https://carbonplan.org/blog/producing-ocr-data).

The commit message encodes per-year pixel counts and a human-readable special
note (e.g. `"None"` for normal tiles, or the no-data explanation for tiles with
no MODIS coverage). This makes the Icechunk commit history directly queryable for
pipeline statistics without any external log — `get_processing_status_gdf` parses
it to populate the status GeoDataFrame.

---

## Reading the Result

```python
import icechunk, xarray as xr

storage = icechunk.azure_storage(
    account="...", container="...", prefix="modis-lst-demo", sas_token="..."
)
repo = icechunk.Repository.open(storage)
session = repo.readonly_session("main")

ds = xr.open_zarr(session.store, zarr_format=3, consolidated=False)
# Scale factor applied during processing; values are in Kelvin. Mask fill value (0 = no data).
lst_k = ds["avg_daytime_lst"].where(ds["avg_daytime_lst"] > 0)
```

---

## Processing in Practice

The progression below shows the pipeline running end-to-end, visualized using
notebook `02_processing_status.ipynb` which calls `get_processing_status_gdf`
to query tile status directly from the Icechunk commit history.

**1. Determining which tiles to process** — `generate_tile_matrix.py` queries
unprocessed land tiles from the Icechunk history and outputs the job matrix:

![Tile matrix generation — workflow logic for determining which tiles to process](https://github.com/user-attachments/assets/3eecfd67-7f1a-4fb3-8eee-3871a5eccd5b)

**2. After initialization, before processing** — the store exists with metadata
only; all land tiles are unprocessed:

![Tile status after initialization — all land tiles unprocessed](https://github.com/user-attachments/assets/44f15446-4e67-4348-b199-b4ff08bc055a)

**3. Mid-run** — the `Process All Tiles` workflow is in flight; tiles are being
committed concurrently as runners finish:

![Tile status mid-run — jobs committing concurrently as runners finish](https://github.com/user-attachments/assets/02e2bdd3-6f77-4356-9380-ba10ba2e2422)

**4. After first run** — nearly complete, with one tile still unprocessed:

![Tile status after first run — one tile remaining unprocessed](https://github.com/user-attachments/assets/51c70095-2260-48c0-a653-cd845c3fa0d1)

**5. After re-running** — the workflow is idempotent; it picks up only the
remaining tiles and finishes:

![Tile status after second run — all tiles processed](https://github.com/user-attachments/assets/77cb2a3b-9a24-45cd-8468-7beb195999d3)

### Results

| Stat | Value |
| --- | --- |
| Land tiles | 381 |
| Processed | 376 |
| No-data (no MODIS coverage) | 5 |
| Unprocessed | 0 |
| Total input data processed | 752.98 GB (250,992 granules from Planetary Computer) |
| Output Zarr store size | 1.17 GB (5,188 objects in Azure Blob) |
| GitHub Actions run time | ~40 minutes |

The 752 GB reflects the total volume of raw MODIS granules downloaded and processed
across all tiles and years. The 1.17 GB output is the resulting analytical store —
annual mean and max summaries rather than the full 8-day time series.

---

## Quick Start

### 1. Fork and clone this repository

### 2. Create an Azure Blob Storage container

Any Azure Blob container works. Note the account name, container name, and
generate a SAS token with read+write permissions.

### 3. Set GitHub repository secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Description |
| --- | --- |
| `AZURE_STORAGE_ACCOUNT` | Azure storage account name |
| `AZURE_STORAGE_SAS_TOKEN` | SAS token with read/write access |
| `AZURE_CONTAINER` | Container name |
| `ICECHUNK_PREFIX` | Path prefix within the container, e.g. `modis-lst-demo` |

### 4. Initialize the store

Run notebook `notebooks/01_initialize_and_setup.ipynb` once locally.
This creates `tile_list.geojson` (commit it to the repo) and the empty Icechunk
repository with metadata only — no data chunks.

### 5. Process all tiles

Run the **Process All Tiles** workflow from the Actions tab. It will:

- Read `tile_list.geojson` and the Icechunk commit history to find unprocessed land tiles (~381)
- Dispatch one GitHub Actions job per tile (all in parallel)
- Each job fetches MODIS LST from Planetary Computer, computes annual stats,
  and commits results to the store

Re-run whenever needed; the workflow is idempotent.

---

## Repository structure

```text
icechunk_github_actions_demo/
├── pixi.toml
├── tile_list.geojson               # all 648 tiles with land boolean; committed
├── config/
│   ├── config_v1.txt               # dataset params + credentials as ENV placeholders
│   └── config_with_secrets_v1.txt  # literal credentials for local runs (gitignored)
├── icechunk_github_actions_demo/   # Python package
│   ├── __init__.py                 # exports Config, get_processing_status_gdf, list_processed_tiles
│   ├── config.py                   # Config class, geobox utilities, commit message constants
│   └── processing.py               # fetch_annual_lst
├── scripts/
│   ├── generate_tile_matrix.py     # prints JSON matrix of unprocessed tiles
│   └── process_tile.py             # fetches + commits one tile
├── notebooks/
│   ├── 01_initialize_and_setup.ipynb   # run once to create tile_list.geojson and the store
│   └── 02_processing_status.ipynb      # visualize processing progress
├── map/                            # interactive map (Next.js + zarr-layer → GitHub Pages)
└── .github/workflows/
    ├── process_all_tiles.yml       # main workflow: generates batch list, calls process_tile_batch.yml per batch
    ├── process_tile_batch.yml      # reusable workflow: matrix of up to 256 tiles for one batch
    ├── process_single_tile.yml     # manual dispatch for testing/reprocessing one tile
    └── deploy-map.yml              # builds and deploys the interactive map to GitHub Pages
```

---

## Scaling Beyond 256 Tiles

GitHub Actions matrix jobs are capped at 256 entries. This demo has 381 land
tiles, which exceeds that limit. The workflows use a **batches-of-batches**
pattern to handle this transparently:

1. `generate-batches` queries unprocessed tiles, outputs a small matrix of batch
   indices (e.g. `{"batch_index": [0, 1]}` for 381 tiles → 2 batches)
2. `process-batches` fans out one job per batch index, each calling
   `process_tile_batch.yml` (a reusable `workflow_call` workflow) with its batch index
3. Each `process_tile_batch.yml` run generates its own ≤256-tile matrix and
   processes them in parallel

The batch size is set by `BATCH_SIZE = 256` in `scripts/generate_tile_matrix.py`.
For very large datasets (thousands of tiles), you can reduce the batch size or
use a different compute backend entirely (Modal, Coiled, Lithops).

---

## Design Tradeoffs

This section compares the approaches taken here against alternatives seen in
related projects, to help you choose the right pattern for your dataset.

### Store initialization

| Approach | When to use |
| --- | --- |
| **Notebook + `dask.full` + `to_zarr(compute=False)`** (this demo) | Interactive; run once before triggering CI. Tile geometries are derived from the same `GeoboxTiles` object that defines the store grid, so coordinate alignment is guaranteed by construction. Good default choice. |
| `xr_zeros` from `odc.geo` + direct Zarr array writes | Convenient shorthand when already using odc.geo geoboxes; skips xarray for the actual writes. Used in [serverless-datacube-demo](https://github.com/earth-mover/serverless-datacube-demo). |
| Direct `zarr.open` + array assignment | Maximum control over encoding; bypasses xarray. Useful when you need Zarr v3 features (ShardingCodec) that xarray doesn't expose yet. |

### Region determination

| Approach | When to use |
| --- | --- |
| **Explicit integer slices** (this demo) | Simplest and most reliable when tiles align exactly with the output grid. No floating-point precision issues; no need to read store coordinates first. |
| `region='auto'` + coordinate snapping | Works for any tile system, including irregular grids. Tile coordinates are snapped to the store's exact values via `sel(..., method='nearest')` + `assign_coords()` before writing. Used in [global_snowmelt_runoff_onset](https://github.com/egagli/global_snowmelt_runoff_onset) and [MODIS_snow_phenology](https://github.com/egagli/MODIS_snow_phenology). |
| Custom index lookup (`get_region`) | Used in the [GLAD ingestion notebook](https://icechunk.io/en/stable/guides/ingestion/glad-ingest/): derives array indices from geographic bounds via coordinate lookups. More explicit but requires knowing the coordinate→index mapping. |
| Direct Zarr array write | Bypasses xarray entirely; computes integer slices manually and writes `target_array[slice] = data`. Used in [serverless-datacube-demo](https://github.com/earth-mover/serverless-datacube-demo). Fastest for simple cases but loses CF metadata handling. |

### Conflict handling and versioning

| Approach | When to use |
| --- | --- |
| **`ConflictDetector()` + Icechunk** (this demo) | Best default: ACID commits, full version history, automatic rebase for non-overlapping writes. Any failure leaves the store in a clean state. The optimistic-concurrency retry loop is based on the pattern described in [CarbonPlan's OCR pipeline post](https://carbonplan.org/blog/producing-ocr-data) and the [Icechunk GLAD ingestion guide](https://icechunk.io/en/stable/guides/ingestion/glad-ingest/). |
| Plain Zarr region writes (no Icechunk) | Works safely with non-overlapping tiles and a shared object store (e.g., S3/Azure). No versioning or rollback. Simpler if you don't need audit trail. Used in older pipeline versions of [global_snowmelt_runoff_onset](https://github.com/egagli/global_snowmelt_runoff_onset). |
| Arraylake / managed Icechunk | Hosted Icechunk with additional features (access control, branch management). Used in [serverless-datacube-demo](https://github.com/earth-mover/serverless-datacube-demo). |

### Tile status tracking

| Approach | When to use |
| --- | --- |
| **Icechunk commit history** (this demo) | No external log to maintain. Commit messages encode per-year pixel counts and a special note. `get_processing_status_gdf(repo, tile_list_path, years)` is shared between CI scripts and the status notebook, returning a GeoDataFrame with `status` (`"processed"`, `"nodata"`, `"unprocessed"`, `"ocean"`) and per-year pixel-count columns. Works as long as commit messages follow a consistent format. Approach inspired by the [Icechunk GLAD ingestion guide](https://icechunk.io/en/stable/guides/ingestion/glad-ingest/). |
| CSV artifacts + consolidation workflow | Used in [global_snowmelt_runoff_onset](https://github.com/egagli/global_snowmelt_runoff_onset): per-tile CSVs uploaded as artifacts, merged by a separate workflow. Good when you want rich per-tile metadata (timing, error messages, pixel counts). |
| GeoJSON + GitHub API dual-source | Used in [MODIS_snow_phenology](https://github.com/egagli/MODIS_snow_phenology): Icechunk history for successes, GitHub Actions job API for failures with log excerpts. Visualizable as a map; most robust failure attribution. |

### Serverless compute backend

| Approach | When to use |
| --- | --- |
| **GitHub Actions** (this demo) | Free for public repos, no additional accounts. Ideal for demos and moderate workloads (~381 tiles). 6-hour job limit; 256-job matrix limit per run. The matrix and reusable workflow patterns used here are covered in the [SciPy 2024 GitHub Actions for Science tutorial](https://scipy2024-githubactionstutorial.readthedocs.io/en/latest/intro.html) ([repo](https://github.com/uwescience/SciPy2024-GitHubActionsTutorial)). |
| Modal / Lithops / Coiled | Higher throughput, shorter cold-start, no matrix limit. Required for very large tile counts or tight latency requirements. Needs additional accounts and cost management. Used in [earthmover's serverless-datacube-demo](https://github.com/earth-mover/serverless-datacube-demo) ([blog post](https://www.earthmover.io/blog/serverless-datacube-pipeline/)). |
| Coiled (with Icechunk) | Dask-native; good fit if your processing already uses Dask clusters. Used in [CarbonPlan's OCR pipeline](https://carbonplan.org/blog/producing-ocr-data). |

---

## Configuration

All tuneable parameters are in [`config/config_v1.txt`](config/config_v1.txt):

```ini
YEARS = 2020,2021,2022
RESOLUTION = 0.01
TILE_SIZE_DEG = 10.0
PIXELS_PER_TILE = 1000
TILE_ROWS = 18
TILE_COLS = 36
FILL_VALUE = 0
TILE_LIST_PATH = tile_list.geojson
AZURE_STORAGE_ACCOUNT = ENV
AZURE_STORAGE_SAS_TOKEN = ENV
AZURE_CONTAINER = ENV
ICECHUNK_PREFIX = ENV
```

Fields set to `ENV` are resolved from environment variables at runtime.
For local runs, copy to `config/config_with_secrets_v1.txt` (gitignored) and
fill in the actual credential values.

Parsed at runtime by the `Config` class from the `icechunk_github_actions_demo` package:

```python
from icechunk_github_actions_demo import Config
config = Config("config/config_v1.txt")        # CI
config = Config("config/config_with_secrets_v1.txt")  # local
```

To adapt this demo for a different dataset, update `config/config_v1.txt`,
re-run notebook `01_initialize_and_setup.ipynb` to regenerate `tile_list.geojson`
and reinitialize the store, then replace the data fetching logic in
`icechunk_github_actions_demo/processing.py`.
