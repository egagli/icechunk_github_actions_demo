declare module '@carbonplan/colormaps' {
  type ColormapFormat = 'hex' | 'rgb'
  type ColormapOptions = { format?: ColormapFormat; count?: number }
  export function makeColormap(name: string, options?: ColormapOptions): string[]
  export function useThemedColormap(name: string, options?: ColormapOptions): string[]
}

declare module '@protomaps/basemaps' {
  type Flavor = Record<string, unknown>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  export function layers(source: string, theme: Flavor, opts?: { lang?: string }): any[]
  export function namedFlavor(name: string): Flavor
}
