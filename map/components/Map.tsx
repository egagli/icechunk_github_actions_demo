import React, { useEffect, useMemo, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import { layers, namedFlavor } from '@protomaps/basemaps'
import { ZarrLayer } from '@carbonplan/zarr-layer'
import { makeColormap } from '@carbonplan/colormaps'

// ---------------------------------------------------------------------------
// Store configuration
// ---------------------------------------------------------------------------

const AZURE_BASE =
  'https://uwcryo.blob.core.windows.net/snowmelt/icechunk_github_actions_demo/modis_LST_multiscale_v1'

// ---------------------------------------------------------------------------
// Dataset configuration
// ---------------------------------------------------------------------------

const YEARS = [2020, 2021, 2022] as const
type Year = (typeof YEARS)[number]

// Data is stored as float32 Celsius (273.15 subtracted before writing).
const yearSelector = (y: Year) => ({ year: y })

const VARIABLE_CONFIGS = {
  avg_daytime_lst: {
    label: 'Avg Daytime LST',
    defaultColormap: 'rainbow',
    defaultClim: [-45, 45] as [number, number],
  },
  max_daytime_lst: {
    label: 'Max Daytime LST',
    defaultColormap: 'fire',
    defaultClim: [-35, 55] as [number, number],
  },
} as const

type Variable = keyof typeof VARIABLE_CONFIGS

// ---------------------------------------------------------------------------
// Colormap options (subset of @carbonplan/colormaps)
// ---------------------------------------------------------------------------

const COLORMAPS = [
  'rainbow', 'fire', 'earth', 'water', 'warm', 'cool',
  'reds', 'oranges', 'yellows', 'greens', 'teals', 'blues',
  'purples', 'pinks', 'greys', 'wind', 'heart', 'sinebow',
  'pinkgreen', 'redteal', 'orangeblue', 'yellowpurple',
]

// ---------------------------------------------------------------------------
// Basemap
// ---------------------------------------------------------------------------

// PMTiles protocol is stateful — register once per page load.
let pmtilesRegistered = false

const BASEMAP_THEME = { ...namedFlavor('black'), background: '#1b1e23', earth: '#1b1e23' }

// Protomaps assets CDN has complete Noto Sans coverage across all Unicode ranges.
// The CarbonPlan S3 CDN is missing many non-Latin ranges, causing 404s for city labels.
const GLYPHS_URL =
  'https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf'

const TILES_URL =
  'pmtiles://https://carbonplan-maps.s3.us-west-2.amazonaws.com/basemaps/pmtiles/global.pmtiles'

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const BG = '#1b1e23'
const ACCENT = '#1dbd8f'
const BORDER = '#2e3138'
const TEXT = '#d0d0d0'
const DIM = '#6b7280'

// ---------------------------------------------------------------------------
// Click info type
// ---------------------------------------------------------------------------

type ClickInfo = {
  lng: number
  lat: number
  status: 'querying' | 'done'
  valueC: number | null
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Map() {
  const mapContainer = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const layerRef = useRef<InstanceType<typeof ZarrLayer> | null>(null)
  const markerRef = useRef<maplibregl.Marker | null>(null)

  // Map state
  const [globeProjection, setGlobeProjection] = useState(true)
  const [mapLoaded, setMapLoaded] = useState(false)
  const [isLoading, setIsLoading] = useState(false)

  // Data controls
  const [year, setYear] = useState<Year>(2020)
  const [variable, setVariable] = useState<Variable>('avg_daytime_lst')
  const [colormap, setColormap] = useState<string>(
    VARIABLE_CONFIGS.avg_daytime_lst.defaultColormap
  )
  const [clim, setClim] = useState<[number, number]>(
    VARIABLE_CONFIGS.avg_daytime_lst.defaultClim
  )
  const [climInputs, setClimInputs] = useState<[string, string]>(['-45', '45'])
  const [opacity, setOpacity] = useState(1)

  // Click state
  const [clickInfo, setClickInfo] = useState<ClickInfo | null>(null)

  // Derived colormap array (memoized — recomputed only when colormap name changes)
  const colormapArray = useMemo(
    () => makeColormap(colormap, { format: 'hex' }),
    [colormap]
  )
  const gradient = `linear-gradient(to right, ${colormapArray.join(', ')})`

  // -- Map initialization ---------------------------------------------------
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return

    if (!pmtilesRegistered) {
      const protocol = new Protocol()
      maplibregl.addProtocol('pmtiles', protocol.tile)
      pmtilesRegistered = true
    }

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        projection: { type: 'globe' },
        version: 8,
        glyphs: GLYPHS_URL,
        sources: {
          protomaps: {
            type: 'vector',
            url: TILES_URL,
            attribution:
              '<a href="https://protomaps.com">Protomaps</a>, © <a href="https://openstreetmap.org">OpenStreetMap</a>',
          },
        },
        layers: layers('protomaps', BASEMAP_THEME, { lang: 'en' }),
      },
      center: [0, 30],
      zoom: 2,
    })

    map.on('styleimagemissing', () => {})
    mapRef.current = map
    map.on('load', () => setMapLoaded(true))

    return () => {
      map.remove()
      mapRef.current = null
      setMapLoaded(false)
    }
  }, [])

  // -- Projection toggle (no map recreation needed) -------------------------
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return
    mapRef.current.setProjection(
      globeProjection ? { type: 'globe' } : { type: 'mercator' }
    )
  }, [mapLoaded, globeProjection])

  // -- ZarrLayer (recreated when variable changes) --------------------------
  useEffect(() => {
    if (!mapLoaded || !mapRef.current) return
    const map = mapRef.current

    try {
      if (map.getLayer('zarr-layer')) map.removeLayer('zarr-layer')
    } catch {}

    const zarrLayer = new ZarrLayer({
      id: 'zarr-layer',
      source: AZURE_BASE,
      variable,
      clim,
      colormap: colormapArray,
      opacity,
      selector: yearSelector(year),
      zarrVersion: 3,
      onLoadingStateChange: ({ loading }: { loading: boolean }) =>
        setIsLoading(loading),
    })

    try {
      map.addLayer(zarrLayer, 'landuse_pedestrian')
    } catch {
      map.addLayer(zarrLayer)
    }
    layerRef.current = zarrLayer

    const clickHandler = async (event: maplibregl.MapMouseEvent) => {
      const layer = layerRef.current
      if (!layer) return

      const { lng, lat } = event.lngLat

      // Place / move persistent marker
      markerRef.current?.remove()
      markerRef.current = new maplibregl.Marker({ color: ACCENT })
        .setLngLat([lng, lat])
        .addTo(map)

      setClickInfo({ lng, lat, status: 'querying', valueC: null })

      const result = await layer.queryData({
        type: 'Point',
        coordinates: [lng, lat],
      })
      const vals = result?.[variable]
      const rawC = Array.isArray(vals) ? vals[0] : null
      setClickInfo({
        lng,
        lat,
        status: 'done',
        valueC: typeof rawC === 'number' && !isNaN(rawC) ? rawC : null,
      })
    }

    map.on('click', clickHandler)

    return () => {
      map.off('click', clickHandler)
      try {
        if (map.getLayer('zarr-layer')) map.removeLayer('zarr-layer')
      } catch {}
      layerRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapLoaded, variable])

  // -- Live updates (no layer recreation) -----------------------------------
  useEffect(() => {
    layerRef.current?.setSelector(yearSelector(year))
  }, [year])

  useEffect(() => {
    const layer = layerRef.current
    if (!layer) return
    layer.setColormap(colormapArray)
    layer.setClim(clim)
  }, [colormap, clim, colormapArray])

  useEffect(() => {
    layerRef.current?.setOpacity(opacity)
  }, [opacity])

  // -- Variable change: reset colormap + clim to per-variable defaults ------
  const handleVariableChange = (v: Variable) => {
    const cfg = VARIABLE_CONFIGS[v]
    setVariable(v)
    setColormap(cfg.defaultColormap)
    setClim(cfg.defaultClim)
    setClickInfo(null)
    markerRef.current?.remove()
    markerRef.current = null
  }

  // -- Clim text inputs -----------------------------------------------------
  const commitClimInput = (index: 0 | 1, value?: string) => {
    const val = parseFloat(value ?? climInputs[index])
    if (Number.isFinite(val)) {
      setClim((prev) => (index === 0 ? [val, prev[1]] : [prev[0], val]))
    } else {
      setClimInputs([String(clim[0]), String(clim[1])])
    }
  }

  const handleClimInputChange = (index: 0 | 1, raw: string) => {
    setClimInputs((prev) => (index === 0 ? [raw, prev[1]] : [prev[0], raw]))
  }

  // Keep text inputs in sync when clim changes externally (variable reset)
  useEffect(() => {
    setClimInputs([String(clim[0]), String(clim[1])])
  }, [clim])

  // -- Render ---------------------------------------------------------------
  const climMid = (clim[0] + clim[1]) / 2

  return (
    <div
      style={{
        position: 'relative',
        width: '100vw',
        height: '100vh',
        background: BG,
        overflow: 'hidden',
        fontFamily: 'system-ui, -apple-system, sans-serif',
      }}
    >
      {/* Map canvas */}
      <div ref={mapContainer} style={{ position: 'absolute', inset: 0 }} />

      {/* Sidebar */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          bottom: 0,
          width: 284,
          background: 'rgba(22,25,30,0.96)',
          borderRight: `1px solid ${BORDER}`,
          backdropFilter: 'blur(6px)',
          display: 'flex',
          flexDirection: 'column',
          color: TEXT,
          fontSize: 13,
          zIndex: 10,
          overflowY: 'auto',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '20px 18px 14px',
            borderBottom: `1px solid ${BORDER}`,
            flexShrink: 0,
          }}
        >
          <div style={{ fontSize: 17, fontWeight: 700, color: '#fff', marginBottom: 2 }}>
            MODIS LST
          </div>
          <div style={{ fontSize: 11, color: DIM, lineHeight: 1.4 }}>
            MODIS MYD11C3 · Land Surface Temperature
            <br />
            0.01° (~1 km) · Annual mean &amp; max
          </div>
        </div>

        {/* Controls */}
        <div
          style={{
            flex: 1,
            padding: '16px 18px',
            display: 'flex',
            flexDirection: 'column',
            gap: 20,
          }}
        >
          {/* Variable */}
          <Section label="Variable">
            {(Object.keys(VARIABLE_CONFIGS) as Variable[]).map((v) => (
              <button
                key={v}
                onClick={() => handleVariableChange(v)}
                style={chipStyle(v === variable)}
              >
                {VARIABLE_CONFIGS[v].label}
              </button>
            ))}
          </Section>

          {/* Year */}
          <Section label="Year">
            <div style={{ display: 'flex', gap: 6 }}>
              {YEARS.map((y) => (
                <button
                  key={y}
                  onClick={() => setYear(y)}
                  style={{ ...chipStyle(y === year), flex: 1, textAlign: 'center' }}
                >
                  {y}
                </button>
              ))}
            </div>
          </Section>

          {/* Colormap */}
          <Section label="Colormap">
            <select
              value={colormap}
              onChange={(e) => setColormap(e.target.value)}
              style={{
                width: '100%',
                padding: '6px 8px',
                borderRadius: 4,
                background: '#1e2128',
                color: TEXT,
                border: `1px solid ${BORDER}`,
                fontSize: 13,
                cursor: 'pointer',
              }}
            >
              {COLORMAPS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <div style={{ height: 10, borderRadius: 3, marginTop: 8, background: gradient }} />
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                marginTop: 3,
                fontSize: 11,
                color: DIM,
              }}
            >
              <span>{clim[0]}°</span>
              <span>{climMid.toFixed(0)}°</span>
              <span>{clim[1]}°</span>
            </div>
          </Section>

          {/* Range */}
          <Section label="Range (°C)">
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input
                type="number"
                value={climInputs[0]}
                onChange={(e) => handleClimInputChange(0, e.target.value)}
                onBlur={() => commitClimInput(0)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitClimInput(0)
                }}
                style={numInputStyle}
              />
              <div style={{ flex: 1, height: 6, borderRadius: 3, background: gradient }} />
              <input
                type="number"
                value={climInputs[1]}
                onChange={(e) => handleClimInputChange(1, e.target.value)}
                onBlur={() => commitClimInput(1)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitClimInput(1)
                }}
                style={numInputStyle}
              />
            </div>
          </Section>

          {/* Opacity */}
          <Section label={`Opacity — ${Math.round(opacity * 100)}%`}>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={opacity}
              onChange={(e) => setOpacity(Number(e.target.value))}
              style={{ width: '100%', accentColor: ACCENT, cursor: 'pointer' }}
            />
          </Section>

          {/* Click result */}
          {clickInfo && (
            <div
              style={{
                padding: '12px 14px',
                background: '#1e2128',
                borderRadius: 6,
                border: `1px solid ${BORDER}`,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 10,
                }}
              >
                <div style={{ fontSize: 11, color: DIM }}>Selected point</div>
                <button
                  onClick={() => {
                    setClickInfo(null)
                    markerRef.current?.remove()
                    markerRef.current = null
                  }}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: DIM,
                    cursor: 'pointer',
                    fontSize: 18,
                    lineHeight: 1,
                    padding: 0,
                  }}
                  aria-label="Clear marker"
                >
                  ×
                </button>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12 }}>
                <CoordRow label="Lat" value={`${clickInfo.lat.toFixed(4)}°`} />
                <CoordRow label="Lon" value={`${clickInfo.lng.toFixed(4)}°`} />
              </div>
              <div style={{ fontSize: 22, fontWeight: 700, color: '#fff', lineHeight: 1 }}>
                {clickInfo.status === 'querying'
                  ? 'Querying…'
                  : clickInfo.valueC !== null
                  ? `${clickInfo.valueC.toFixed(1)} °C`
                  : 'No data'}
              </div>
            </div>
          )}

          {/* Projection */}
          <Section label="Projection">
            <div style={{ display: 'flex', gap: 6 }}>
              {[
                { label: 'Globe', value: true },
                { label: 'Mercator', value: false },
              ].map((opt) => (
                <button
                  key={String(opt.value)}
                  onClick={() => setGlobeProjection(opt.value)}
                  style={{
                    ...chipStyle(globeProjection === opt.value),
                    flex: 1,
                    textAlign: 'center',
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </Section>

          {/* Status messages */}
          {isLoading && <StatusRow>Loading chunks…</StatusRow>}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '10px 18px',
            borderTop: `1px solid ${BORDER}`,
            fontSize: 10,
            color: '#444',
            lineHeight: 1.5,
            flexShrink: 0,
          }}
        >
          Data: NASA MODIS MYD11C3 v6.1
          <br />
          Powered by{' '}
          <a href="https://github.com/earth-mover/icechunk" style={{ color: '#555' }}>
            Icechunk
          </a>{' '}
          +{' '}
          <a href="https://github.com/carbonplan/zarr-layer" style={{ color: '#555' }}>
            zarr-layer
          </a>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          color: DIM,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          fontWeight: 600,
          marginBottom: 8,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  )
}

function CoordRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
      <span style={{ color: DIM }}>{label}</span>
      <span style={{ color: TEXT, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </span>
    </div>
  )
}

function StatusRow({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 12, color: DIM, display: 'flex', alignItems: 'center', gap: 8 }}>
      <span
        style={{
          display: 'inline-block',
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: ACCENT,
        }}
      />
      {children}
    </div>
  )
}

const chipStyle = (active: boolean): React.CSSProperties => ({
  display: 'block',
  width: '100%',
  textAlign: 'left',
  padding: '7px 10px',
  marginBottom: 5,
  cursor: 'pointer',
  background: active ? ACCENT : 'transparent',
  color: active ? '#000' : TEXT,
  border: `1px solid ${active ? ACCENT : BORDER}`,
  borderRadius: 4,
  fontSize: 12,
  fontWeight: active ? 700 : 400,
})

const numInputStyle: React.CSSProperties = {
  width: 58,
  padding: '5px 7px',
  borderRadius: 4,
  background: '#1e2128',
  color: TEXT,
  border: `1px solid ${BORDER}`,
  fontSize: 13,
}
