import { Html, Head, Main, NextScript } from 'next/document'

// Google tag (gtag.js) — GA4 property shared with egagli.github.io.
// Inside egagli.github.io/maps/*.html the wrapper page already counted this
// visit, so skip the page view there and mark events as embedded.
const GA_ID = 'G-M59931E34K'
const GA_INIT = `
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  var gaEmbedded = window.self !== window.top;
  gtag('set', { embedded: gaEmbedded });
  gtag('config', '${GA_ID}', { send_page_view: !gaEmbedded });
`

export default function Document() {
  return (
    <Html lang="en">
      <Head>
        <script async src={`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`} />
        <script dangerouslySetInnerHTML={{ __html: GA_INIT }} />
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  )
}
