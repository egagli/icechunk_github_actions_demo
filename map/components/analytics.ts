// Tiny GA4 event helper. The gtag snippet lives in pages/_document.tsx; this
// never throws if gtag is missing (blocked, offline, dev).
type GtagParams = Record<string, string | number | boolean>

declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void
  }
}

export function track(name: string, params: GtagParams = {}): void {
  try {
    if (typeof window !== 'undefined' && typeof window.gtag === 'function') {
      window.gtag('event', name, params)
    }
  } catch {
    // analytics must never break the map
  }
}
