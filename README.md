# icechunk-github-actions-demo

A minimum reproducible example of building a **global-scale raster dataset** using
GitHub Actions as free compute and [Icechunk](https://icechunk.io) as a versioned
Zarr v3 store. Each GitHub Actions runner processes one spatial tile; all runners
write to the same store concurrently without any external coordination.

The concrete dataset is annual average and maximum MODIS daytime land surface
temperature ([MOD11A2 v6.1](https://lpdaac.usgs.gov/products/mod11a2v061/)) for
2020–2022, stored globally at 0.01° (~1 km) in EPSG:4326.

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                    Azure Blob Storage                        │
│              Icechunk store (Zarr v3)                        │
│   avg_daytime_lst[year, latitude, longitude]  uint16         │
│   max_daytime_lst[year, latitude, longitude]  uint16         │
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

## Repository structure

```text
icechunk_github_actions_demo/
├── pixi.toml
├── tile_list.geojson               # all 648 tiles with land boolean; committed
├── config/
│   ├── config_v1.txt               # dataset params + credentials as ENV placeholders
│   └── config_with_secrets_v1.txt  # literal credentials for local runs (gitignored)
├── icechunk_github_actions_demo/   # Python package
│   ├── __init__.py                 # exports Config, load_tile_list, processed_tiles
│   ├── config.py                   # Config class, geobox utilities
│   └── processing.py               # fetch_annual_lst
├── scripts/
│   ├── generate_tile_matrix.py     # prints JSON matrix of unprocessed tiles
│   └── process_tile.py             # fetches + commits one tile
├── notebooks/
│   ├── 01_initialize_and_setup.ipynb   # run once to create tile_list.geojson and the store
│   └── 02_processing_status.ipynb      # visualize processing progress
└── .github/workflows/
    ├── process_all_tiles.yml       # main workflow: matrix over all unprocessed tiles
    └── process_single_tile.yml     # manual dispatch for testing/reprocessing one tile
```

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

## How It Works

### Step 1: Initialize the store (notebook `01_initialize_and_setup.ipynb`)

Run this notebook once before any tile processing. It does two things:

**1a. Build `tile_list.geojson`** — derives all 648 tile geometries from the
global GeoBox so they are provably consistent with the output store grid, then
marks each tile with a `land` boolean via Natural Earth polygons. Commit this
file; it is read by CI without recomputation.

**1b. Create the empty store** — an empty xarray Dataset is constructed with
the correct shape, dimensions, and encoding, backed by dask arrays that are
never materialized. Writing with `compute=False` and `write_empty_chunks=False`
creates only metadata and coordinates; no data chunks exist until runners fill them.

```python
shape = (3, 18000, 36000)   # years × lat × lon

ds = xr.Dataset({
    "avg_daytime_lst": xr.DataArray(
        da.full(shape, np.uint16(0), dtype=np.uint16, chunks=(1, 1000, 1000)),
        dims=["year", "latitude", "longitude"],
        attrs={"scale_factor": np.float32(0.02), "units": "K", ...},
    ),
    ...
}, coords={"year": [2020, 2021, 2022], "latitude": lats, "longitude": lons})

repo = icechunk.Repository.create(storage)
session = repo.writable_session("main")
ds.to_zarr(session.store, mode="w", zarr_format=3,
           compute=False, write_empty_chunks=False, consolidated=False)
session.commit("initialize store: empty template")
```

### Step 2: Generate the tile matrix (`scripts/generate_tile_matrix.py`)

The `generate-matrix` job runs first and outputs a JSON list of unprocessed
tiles. It determines which tiles need processing by:

1. Reading `tile_list.geojson` via `load_tile_list()` (returns only `land=True` tiles)
2. Calling `processed_tiles(repo)` to parse the Icechunk commit history for
   messages matching `tile_R_C: processed`
3. Subtracting processed from all land tiles

**No separate status log is maintained.** The Icechunk commit history is the
single source of truth. Both functions are provided by the
`icechunk_github_actions_demo` package and reused by notebook `02_processing_status.ipynb`.

```python
from icechunk_github_actions_demo import Config, load_tile_list, processed_tiles

tile_gdf = load_tile_list()   # reads tile_list.geojson, filters land=True
land = [{"row": int(r["row"]), "col": int(r["col"])} for _, r in tile_gdf.iterrows()]

repo = icechunk.Repository.open(storage)
done = processed_tiles(repo)  # parses commit history

unprocessed = [t for t in land if (t["row"], t["col"]) not in done]
print(json.dumps({"tile": unprocessed}))
```

The GitHub Actions matrix then fans out one job per tile:

```yaml
strategy:
  fail-fast: false
  matrix: ${{ fromJson(needs.generate-matrix.outputs.matrix) }}
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
avg_lst, max_lst = fetch_annual_lst(tile_geobox, year, config.PIXELS_PER_TILE)
```

Inside `fetch_annual_lst`:

```python
bbox = tile_geobox.boundingbox
items = catalog.search(
    collections=["modis-11A2-061"],
    bbox=[bbox.left, bbox.bottom, bbox.right, bbox.top],
    datetime=f"{year}-01-01/{year}-12-31",
).item_collection()

ds = odc.stac.load(items, bands=["LST_Day_1km", "QC_Day"], geobox=tile_geobox, ...)
good = (ds.QC_Day & 0b11) <= 1
lst = ds.LST_Day_1km.where(good).where(ds.LST_Day_1km >= 7500)
avg_lst = lst.mean("time").compute().astype(np.uint16)
max_lst = lst.max("time").compute().astype(np.uint16)
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
            f"tile_{tile_row}_{tile_col}: processed",
            rebase_with=icechunk.ConflictDetector(),
        )
        break

    except Exception as exc:
        time.sleep(random.uniform(3, 10))  # retry on rare timing conflict
```

`ConflictDetector` automatically rebases the commit on top of any concurrent
commits. Because every tile writes to a spatially disjoint region, there are
never real data conflicts — only commit timing collisions, which always resolve.

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
# Apply scale factor to get Kelvin: 0 means no data
lst_k = ds["avg_daytime_lst"].where(ds["avg_daytime_lst"] > 0) * 0.02
```

---

## Scaling Beyond 256 Tiles

GitHub Actions matrix jobs are capped at 256 entries. For datasets with more
land tiles (finer tile grids, different regions), use a **batches-of-batches**
pattern: a first workflow splits the tile list into 256-tile batches and calls a
second workflow as a reusable [`workflow_call`](https://docs.github.com/en/actions/sharing-automations/reusing-workflows)
for each batch. See [`process_batch_large.yml`](https://github.com/egagli/global_snowmelt_runoff_onset/blob/main/.github/workflows/process_batch_large.yml)
in `global_snowmelt_runoff_onset` for a worked example.

This demo has 381 land tiles (at 10°×10° resolution), which exceeds the 256-job
limit. To run the full dataset you will need the batches-of-batches pattern linked above.

---

## Design Tradeoffs

This section compares the approaches taken here against alternatives seen in
related projects, to help you choose the right pattern for your dataset.

### Store initialization

| Approach | When to use |
| --- | --- |
| **Notebook + `dask.full` + `to_zarr(compute=False)`** (this demo) | Interactive; run once before triggering CI. Good default choice. |
| `xr_zeros` from `odc.geo` | Convenient shorthand when already using odc.geo geoboxes; same semantics under the hood. Used in [serverless-datacube-demo](https://github.com/earth-mover/serverless-datacube-demo). |
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
| **`ConflictDetector()` + Icechunk** (this demo) | Best default: ACID commits, full version history, automatic rebase for non-overlapping writes. Any failure leaves the store in a clean state. |
| Plain Zarr region writes (no Icechunk) | Works safely with non-overlapping tiles and a shared object store (e.g., S3/Azure). No versioning or rollback. Simpler if you don't need audit trail. Used in older pipeline versions of [global_snowmelt_runoff_onset](https://github.com/egagli/global_snowmelt_runoff_onset). |
| Arraylake / managed Icechunk | Hosted Icechunk with additional features (access control, branch management). Used in [serverless-datacube-demo](https://github.com/earth-mover/serverless-datacube-demo). |

### Tile status tracking

| Approach | When to use |
| --- | --- |
| **Icechunk commit history** (this demo) | No external log to maintain. Commit messages are the record. The `processed_tiles(repo)` helper is shared between CI scripts and the status notebook. Works as long as commit messages follow a consistent format. |
| CSV artifacts + consolidation workflow | Used in [global_snowmelt_runoff_onset](https://github.com/egagli/global_snowmelt_runoff_onset): per-tile CSVs uploaded as artifacts, merged by a separate workflow. Good when you want rich per-tile metadata (timing, error messages, pixel counts). |
| GeoJSON + GitHub API dual-source | Used in [MODIS_snow_phenology](https://github.com/egagli/MODIS_snow_phenology): Icechunk history for successes, GitHub Actions job API for failures with log excerpts. Visualizable as a map; most robust failure attribution. |

### Serverless compute backend

| Approach | When to use |
| --- | --- |
| **GitHub Actions** (this demo) | Free for public repos, no additional accounts. Ideal for demos and moderate workloads (~381 tiles). 6-hour job limit; 256-job matrix limit per run. |
| Modal / Lithops / Coiled | Higher throughput, shorter cold-start, no matrix limit. Required for very large tile counts or tight latency requirements. Needs additional accounts and cost management. Used in [serverless-datacube-demo](https://github.com/earth-mover/serverless-datacube-demo). |
| Coiled (with Icechunk) | Dask-native; good fit if your processing already uses Dask clusters. Used in [CarbonPlan OCR](https://carbonplan.org/blog/producing-ocr-data). |

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
