import type { AppProps } from 'next/app'
import 'maplibre-gl/dist/maplibre-gl.css'
import '../styles/sheet.css'

export default function App({ Component, pageProps }: AppProps) {
  return <Component {...pageProps} />
}
