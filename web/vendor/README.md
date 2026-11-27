Vendored: @noble/ciphers 2.0.1 (MIT, Paul Miller, audited) - only `gcm` from `@noble/ciphers/aes.js`,
bundled with esbuild (`--bundle --minify --format=iife`), exposes `window.nobleGcm`.
The same bytes are inlined at the top of ../sign.js (no CDN, no extra request; sealed file stays one inline script).
Used only when `crypto.subtle` is unavailable (non-secure contexts, in-app HTML viewers).
sha256 of noble-ciphers-aes-gcm.min.js: 0340805eff78ef16ba572a0cbf1102fa7a9497faddc00a43793293338b171532

Rebuild (no package.json is kept in the repo): `npm i @noble/ciphers@2.0.1 esbuild`, an entry file
`import {gcm} from '@noble/ciphers/aes.js'; window.nobleGcm = gcm;`, then
`npx esbuild entry.js --bundle --minify --format=iife`. Keep the MIT notice (LICENSE.noble-ciphers) with it,
and the header comment in ../sign.js.

Offline PDF assets: pdf-lib 1.17.1 (MIT) and official PDF.js 4.10.38 minified
module/worker (Apache-2.0). See `pdf-sources.json` for pinned official release URLs
and SHA-256 hashes, `LICENSE.pdf-lib`, `LICENSE.pdfjs`, and the root
`THIRD_PARTY_NOTICES.md`. The files are embedded in offline HTML; no CDN is used.
