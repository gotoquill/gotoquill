---
name: gotoquill
description: Get a real human signature on a local PDF. Sends the user an end-to-end encrypted signing link, waits until they sign, then sends the signed PDF back in the chat.
homepage: https://gotoquill.com
metadata:
  {"openclaw": {"emoji": "✍️", "homepage": "https://gotoquill.com", "requires": {"bins": ["gotoquill"]}}}

---

# gotoquill

Use this when the user asks you to sign a PDF, get their signature on a document,
or have someone sign a contract or form.

## Setup (once)

Install Gotoquill, then add the MCP server. It runs locally over stdio and needs no account:

```bash
uv tool install gotoquill
gotoquill mcp
```

For a one-command MCP launcher, use `uvx gotoquill mcp`. Source: https://github.com/gotoquill/gotoquill.

Optional, so you are woken when a signature arrives:
`gotoquill connect` (OpenClaw is auto-detected).

## Flow

1. Call `request_signature(pdf_path=...)` with the absolute path of the PDF.
   Show the user the returned `preview_png_path` (where the signature will go) and
   send them `sign_url` (and the QR code `qr_png_path` if useful). Do not alter the link.
2. Wait in the same turn: call `wait_for_signature(request_id)` (waits up to 600 s).
   If it is still `pending`, call it again, or run `gotoquill wait <request_id>`
   as a background job.
3. When the status is `completed`, **send the file at `signed_pdf_path` back to the
   user in the chat right away, without being asked**. Mention the audit record at
   `audit_path`. Follow the `next` hint in the result.
4. If the status is `declined`, `expired` or `cancelled`, tell the user plainly.
   Use `cancel_request(request_id)` if the user changes their mind.

No network for the signer? Use `delivery="file"` and finish with
`apply_signature_response` once the user sends back the reply file or code.

## Rules

- Only a human can sign. Never sign, draw, or fill a signature yourself.
- Pass `placements` only if the user tells you where to sign; auto-placement is the default.
- Keep the signed PDF on this computer; it is saved next to the original.
