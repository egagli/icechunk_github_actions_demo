YEARS = [2020, 2021, 2022]
RESOLUTION = 0.01        # degrees per pixel
TILE_SIZE_DEG = 10.0     # degrees per tile edge
PIXELS_PER_TILE = int(TILE_SIZE_DEG / RESOLUTION)  # 1000
TILE_ROWS = 18           # 18 rows × 10° = 180° latitude
TILE_COLS = 36           # 36 cols × 10° = 360° longitude
FILL_VALUE = 0           # uint16 fill for missing/masked data
