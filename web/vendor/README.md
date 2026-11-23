Vendored: @noble/ciphers 2.0.1 (MIT, Paul Miller, audited) - only `gcm` from `@noble/ciphers/aes.js`,
bundled with esbuild (`--bundle --minify --format=iife`), exposes `window.nobleGcm`.
The same bytes are inlined at the top of ../sign.js (no CDN, no extra request; sealed file stays one inline script).
Used only when `crypto.subtle` is unavailable (non-secure contexts, in-app HTML viewers).
sha256 of noble-ciphers-aes-gcm.min.js: 0340805eff78ef16ba572a0cbf1102fa7a9497faddc00a43793293338b171532

Rebuild (no package.json is kept in the repo): `npm i @noble/ciphers@2.0.1 esbuild`, an entry file
`import {gcm} from '@noble/ciphers/aes.js'; window.nobleGcm = gcm;`, then
`npx esbuild entry.js --bundle --minify --format=iife`. Keep the MIT notice (LICENSE.noble-ciphers) with it,
and the header comment in ../sign.js.
