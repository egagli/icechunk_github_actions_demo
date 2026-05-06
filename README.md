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

```
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

1. Run `Initialize Store` once — creates the empty Icechunk store
2. Run `Process All Tiles` — queries commit history, dispatches one job per
   unprocessed land tile, each writes its region and commits
3. Re-run `Process All Tiles` at any time — already-processed tiles are
   automatically skipped; only failures or new tiles are re-processed

---

## Quick Start

### 1. Fork and clone this repository

### 2. Create an Azure Blob Storage container

Any Azure Blob container works. Note the account name, container name, and
generate a SAS token with read+write permissions.

### 3. Set GitHub repository secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Description |
|---|---|
| `AZURE_STORAGE_ACCOUNT` | Azure storage account name |
| `AZURE_STORAGE_SAS_TOKEN` | SAS token with read/write access |
| `AZURE_CONTAINER` | Container name |
| `ICECHUNK_PREFIX` | Path prefix within the container, e.g. `modis-lst-demo` |

### 4. Initialize the store

Run the **Initialize Store** workflow once from the Actions tab.
This creates the empty Icechunk repository with metadata only — no data chunks.

### 5. Process all tiles

Run the **Process All Tiles** workflow. It will:
- Query the Icechunk commit history to find unprocessed land tiles (~200)
- Dispatch one GitHub Actions job per tile (all in parallel)
- Each job fetches MODIS LST from Planetary Computer, computes annual stats,
  and commits results to the store

Re-run whenever needed; the workflow is idempotent.

---

## How It Works

### Step 1: Initialize the store (`scripts/initialize_store.py`)

An empty xarray Dataset is constructed with the correct shape, dimensions, and
encoding — but backed by dask arrays that are never materialized. Writing with
`compute=False` and `write_empty_chunks=False` creates only metadata and
coordinates in the Icechunk store; no data chunks exist until runners fill them.

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
session.commit("initialize store: empty template, 2020-2022")
```

### Step 2: Generate the tile matrix (`scripts/generate_tile_matrix.py`)

The `generate-matrix` job runs first and outputs a JSON list of unprocessed
tiles. It determines which tiles need processing by:

1. Computing all land-intersecting tiles (via cartopy)
2. Parsing the Icechunk commit history for messages matching
   `tile_R_C: processed`
3. Subtracting processed from all land tiles

**No separate status log is maintained.** The Icechunk commit history is the
single source of truth.

```python
# All land tiles
land_tiles = [
    {"row": row, "col": col}
    for row in range(18) for col in range(36)
    if LAND.intersecting_geometries((lon_min, lon_max, lat_min, lat_max))
]

# Already processed — from Icechunk commit messages
session = repo.readonly_session("main")
processed = set()
for commit in session.ancestry():
    m = re.match(r"tile_(\d+)_(\d+): processed", commit.message)
    if m:
        processed.add((int(m.group(1)), int(m.group(2))))

unprocessed = [t for t in land_tiles if (t["row"], t["col"]) not in processed]
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

**Data fetching**: `pystac_client` + `odc.stac` load all MOD11A2 granules for
the tile's bounding box and year, reprojected to our 0.01° EPSG:4326 geobox.
`QC_Day` bits 0–1 ≤ 1 selects good/nominal quality pixels; values below 7500
(fill) are excluded.

```python
items = catalog.search(
    collections=["modis-11A2-061"],
    bbox=[lon_min, lat_min, lon_max, lat_max],
    datetime=f"{year}-01-01/{year}-12-31",
).item_collection()

ds = odc.stac.load(items, bands=["LST_Day_1km", "QC_Day"], geobox=geobox, ...)
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
            year_idx = YEARS.index(yr)
            region = {
                "year":      slice(year_idx, year_idx + 1),
                "latitude":  slice(lat_start, lat_start + 1000),
                "longitude": slice(lon_start, lon_start + 1000),
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

This demo's ~200 land tiles fit comfortably within the 256-job limit, so a
single batch is sufficient.

---

## Design Tradeoffs

This section compares the approaches taken here against alternatives seen in
related projects, to help you choose the right pattern for your dataset.

### Store initialization

| Approach | When to use |
|---|---|
| **`dask.full` + `to_zarr(compute=False)`** (this demo) | Simple; works with any xarray Dataset. Good default choice. |
| `xr_zeros` from `odc.geo` | Convenient shorthand when already using odc.geo geoboxes; same semantics under the hood. Used in [serverless-datacube-demo](https://github.com/earth-mover/serverless-datacube-demo). |
| Direct `zarr.open` + array assignment | Maximum control over encoding; bypasses xarray. Useful when you need Zarr v3 features (ShardingCodec) that xarray doesn't expose yet. |

### Region determination

| Approach | When to use |
|---|---|
| **Explicit integer slices** (this demo) | Simplest and most reliable when tiles align exactly with the output grid. No floating-point precision issues; no need to read store coordinates first. |
| `region='auto'` + coordinate snapping | Works for any tile system, including irregular grids. Tile coordinates are snapped to the store's exact values via `sel(..., method='nearest')` + `assign_coords()` before writing. Used in [global_snowmelt_runoff_onset](https://github.com/egagli/global_snowmelt_runoff_onset) and [MODIS_snow_phenology](https://github.com/egagli/MODIS_snow_phenology). |
| Custom index lookup (`get_region`) | Used in the [GLAD ingestion notebook](https://icechunk.io/en/stable/guides/ingestion/glad-ingest/): derives array indices from geographic bounds via coordinate lookups. More explicit but requires knowing the coordinate→index mapping. |
| Direct Zarr array write | Bypasses xarray entirely; computes integer slices manually and writes `target_array[slice] = data`. Used in [serverless-datacube-demo](https://github.com/earth-mover/serverless-datacube-demo). Fastest for simple cases but loses CF metadata handling. |

### Conflict handling and versioning

| Approach | When to use |
|---|---|
| **`ConflictDetector()` + Icechunk** (this demo) | Best default: ACID commits, full version history, automatic rebase for non-overlapping writes. Any failure leaves the store in a clean state. |
| Plain Zarr region writes (no Icechunk) | Works safely with non-overlapping tiles and a shared object store (e.g., S3/Azure). No versioning or rollback. Simpler if you don't need audit trail. Used in older pipeline versions of [global_snowmelt_runoff_onset](https://github.com/egagli/global_snowmelt_runoff_onset). |
| Arraylake / managed Icechunk | Hosted Icechunk with additional features (access control, branch management). Used in [serverless-datacube-demo](https://github.com/earth-mover/serverless-datacube-demo). |

### Tile status tracking

| Approach | When to use |
|---|---|
| **Icechunk commit history** (this demo) | No external log to maintain. Commit messages are the record. Works as long as commit messages follow a consistent format. |
| CSV artifacts + consolidation workflow | Used in [global_snowmelt_runoff_onset](https://github.com/egagli/global_snowmelt_runoff_onset): per-tile CSVs uploaded as artifacts, merged by a separate workflow. Good when you want rich per-tile metadata (timing, error messages, pixel counts). |
| GeoJSON + GitHub API dual-source | Used in [MODIS_snow_phenology](https://github.com/egagli/MODIS_snow_phenology): Icechunk history for successes, GitHub Actions job API for failures with log excerpts. Visualizable as a map; most robust failure attribution. |

### Serverless compute backend

| Approach | When to use |
|---|---|
| **GitHub Actions** (this demo) | Free for public repos, no additional accounts. Ideal for demos and moderate workloads (~200 tiles). 6-hour job limit; 256-job matrix limit per run. |
| Modal / Lithops / Coiled | Higher throughput, shorter cold-start, no matrix limit. Required for very large tile counts or tight latency requirements. Needs additional accounts and cost management. Used in [serverless-datacube-demo](https://github.com/earth-mover/serverless-datacube-demo). |
| Coiled (with Icechunk) | Dask-native; good fit if your processing already uses Dask clusters. Used in [CarbonPlan OCR](https://carbonplan.org/blog/producing-ocr-data). |

---

## Configuration

All tuneable parameters are in [`config.py`](config.py):

```python
YEARS = [2020, 2021, 2022]
RESOLUTION = 0.01        # degrees per pixel
TILE_SIZE_DEG = 10.0     # degrees per tile edge
PIXELS_PER_TILE = 1000   # = TILE_SIZE_DEG / RESOLUTION
TILE_ROWS = 18
TILE_COLS = 36
FILL_VALUE = 0
```

To adapt this demo for a different dataset, update `config.py` and replace the
data fetching logic in `scripts/process_tile.py`.
