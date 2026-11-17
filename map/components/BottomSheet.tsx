import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

// Phones, tablets and landscape phones: the controls live in one bottom sheet, the layout shared by
// every map on egagli.github.io. Three states: peek (the `peek` content, at most 140 px), half (50 %)
// and full (88 %). Tablets get a floating sheet (at most 600 px, centred); landscape phones dock it on
// the left with peek and full only. Styles: styles/sheet.css.

export const SHEET_QUERY = '(max-width: 1023px), (pointer: coarse) and (max-height: 520px)'
const LAND_QUERY = '(pointer: coarse) and (max-height: 520px)'
const TABLET_QUERY = '(min-width: 721px)'

export type SheetState = 'peek' | 'half' | 'full'
/** How much of the map the sheet covers, for the map's padding. */
export type SheetCover = { bottom: number; left: number }

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const update = () => setMatches(mq.matches)
    update()
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [query])
  return matches
}

type Props = {
  title: string
  state: SheetState
  onState: (s: SheetState) => void
  onCover: (c: SheetCover) => void
  peek: React.ReactNode
  children: React.ReactNode
}

export default function BottomSheet({ title, state, onState, onCover, peek, children }: Props) {
  const isLand = useMediaQuery(LAND_QUERY)
  const isTablet = useMediaQuery(TABLET_QUERY)
  const layout = isLand ? 'land' : isTablet ? 'tablet' : 'phone'
  const sheetRef = useRef<HTMLElement>(null)
  const headRef = useRef<HTMLDivElement>(null)
  const peekRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const [dims, setDims] = useState({ peek: 136, half: 300, full: 520, gap: 0 })
  const [dragH, setDragH] = useState<number | null>(null)

  const order: SheetState[] = layout === 'land' ? ['peek', 'full'] : ['peek', 'half', 'full']
  const current: SheetState = order.includes(state) ? state : 'full'

  const measure = useCallback(() => {
    const H = window.innerHeight
    const gap = layout === 'phone' ? 0 : 12
    // header + the body's 6 px top padding + the peek content + 6 px below it
    const natural = (headRef.current?.offsetHeight ?? 44) + (peekRef.current?.offsetHeight ?? 80) + 12
    const full = layout === 'land' ? H - 2 * gap : Math.round(H * 0.88) - gap
    setDims({ peek: Math.round(Math.min(natural, 140, full)), half: Math.round(H * 0.5) - gap, full, gap })
  }, [layout])

  useLayoutEffect(() => { measure() }, [measure, peek])
  useEffect(() => {
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [measure])

  const visible = dragH ?? dims[current]

  // Tell the map how much of it the sheet covers (bottom on phones and tablets, left when docked).
  useEffect(() => {
    if (dragH !== null) return
    if (layout === 'land') onCover({ bottom: 0, left: (sheetRef.current?.offsetWidth ?? 0) + 2 * dims.gap })
    else onCover({ bottom: Math.round(Math.min(dims[current], window.innerHeight * 0.6) + dims.gap), left: 0 })
  }, [current, dims, layout, dragH, onCover])

  useEffect(() => {
    document.documentElement.dataset.sheet = current
    if (current === 'peek' && bodyRef.current) bodyRef.current.scrollTop = 0
    return () => { delete document.documentElement.dataset.sheet }
  }, [current])

  const cycle = () => onState(order[(order.indexOf(current) + 1) % order.length])

  // Drag the header; a tap cycles the states.
  const drag = useRef<{ y0: number; h0: number; moved: boolean; id: number; h: number } | null>(null)
  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button > 0 || (e.target as Element).closest('.m-chev')) return
    drag.current = { y0: e.clientY, h0: dims[current], moved: false, id: e.pointerId, h: dims[current] }
    headRef.current?.setPointerCapture?.(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d || e.pointerId !== d.id) return
    const dy = d.y0 - e.clientY
    if (!d.moved && Math.abs(dy) < 6) return
    d.moved = true
    d.h = Math.max(dims.peek * 0.8, Math.min(dims.full, d.h0 + dy))
    setDragH(d.h)
  }
  const onPointerEnd = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d || e.pointerId !== d.id) return
    drag.current = null
    setDragH(null)
    if (!d.moved) { cycle(); return }
    const bias = Math.sign(d.h - d.h0) * 40   // a short flick still moves one state
    const nearest = order
      .map((s) => [s, Math.abs(dims[s] - (d.h + bias))] as const)
      .sort((a, b) => a[1] - b[1])[0][0]
    onState(nearest)
  }

  const next = current === 'full' || (layout === 'land' && current !== 'peek') ? 'Collapse panel' : 'Expand panel'
  const style = {
    '--sheet-full': `${dims.full}px`,
    '--sheet-vis': `${visible}px`,
  } as React.CSSProperties

  return (
    <section
      ref={sheetRef}
      className={`m-sheet m-${layout}${dragH !== null ? ' m-dragging' : ''}`}
      style={style}
      aria-label="Map controls"
      data-state={current}
      onKeyDown={(e) => { if (e.key === 'Escape' && current !== 'peek') { onState('peek'); headRef.current?.focus() } }}
    >
      <div
        ref={headRef}
        className="m-head"
        role="button"
        tabIndex={0}
        aria-expanded={current !== 'peek'}
        aria-label={`${next}: ${title}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
        onKeyDown={(e) => {
          if (e.target === headRef.current && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); cycle() }
        }}
      >
        <span className="m-pill" aria-hidden="true" />
        <div className="m-title">{title}</div>
        <button type="button" className="m-chev" aria-label={next} onClick={(e) => { e.stopPropagation(); cycle() }}>
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
            <path d="M6 15l6-6 6 6" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
      <div ref={bodyRef} className="m-body">
        <div ref={peekRef} className="m-peek">{peek}</div>
        {children}
      </div>
    </section>
  )
}
