# Changelog

## Local 0.3.0 - 2026-11-27

- Use numeric signing dates, with a remembered American date checkbox and signer timezone handling.
- Center signatures, dates and typed text in their placement boxes, preserving padding and shrinking to fit.
- Offer signed PDF download and sharing immediately after signing.
- Keep spot roles and numbering consistent, including bidirectional Hebrew labels.

- Add root Agent Plugins manifests for the hosted Cloud MCP, supported by Cursor Marketplace, and the official logo asset.
- Fix drawn-signature export after the signing pad closes. Capture before animation, validate visible PNG ink in the browser and Python, and preserve strokes on retry.
- Add true-offline signed PDF download and sharing from the original PDF, using a shared Python/browser stamp plan and vendored pdf-lib and pdf.js. Replace embedded page PNGs with browser rendering and zoom.
- Make a small `.gotoquill` receipt the primary return to chat, keep response codes as a hidden fallback, and record browser and authoritative Python PDF hashes without claiming byte identity.
- Add CLI `--list-spots` and `--spots first|last|all|1,3` for every delivery. Require a choice for multiple candidates and scope dates to selected signature roles.

- Allow unauthenticated initialize, tools/list, ping and notifications/initialized on the hosted MCP endpoint for all clients while tool calls still require OAuth; add an icon to the registry listing.

- Add MCP Registry publishing through GitHub Actions OIDC in the public repository, available manually and after PyPI releases, with version checks, schema validation and a verified publisher download.
- Clarify Local Apache 2.0 licensing and the separate hosted Cloud service. Include the CLA, trademark policy and English/Hebrew Cloud data-handling texts approved on 23 November 2026 (Asia/Jerusalem). CLA signing remains inactive.
- Document the public contribution process: issue templates for bugs, improvements, feature ideas and assistant support requests, GitHub Discussions for questions, and how accepted pull requests reach `main` through an export.

## Local 0.2.0

The exported package declares version 0.2.0. Earlier private development history is not imported. Local 0.2.0 is published on PyPI.
