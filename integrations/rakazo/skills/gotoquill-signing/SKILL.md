---
name: gotoquill-signing
description: Request a real person's signature on a PDF with Gotoquill, help them open the signing page, check progress, and retrieve the signed PDF. Use when the user asks to sign a PDF or collect a signature.
---

1. Gotoquill collects a real person's signature with explicit human consent in the signing UI. Never invent a signature or treat a chat request as signing consent. Form filling and legal advice are outside this workflow.
2. If authentication is required, ask the user to choose **Sign in** or **Connect OAuth** for Gotoquill in **Integrations** and finish in the browser. Never collect credentials in chat.
3. Obtain the intended PDF and signer. Call `request_signature` with a supported PDF input. `prepare_pdf_for_signing` offers fewer request options and also returns a pending request, not a signed PDF. Explain any upload fallback returned by the server.
4. Present the returned `sign_url` as a browser link. A card may appear, but its controls may be limited. Use **Open signing page** or the text link when in-card signing is unavailable.
5. Let the person review the PDF, provide their signature, and explicitly consent in the UI. Do not perform these steps on their behalf.
6. Call `get_signature_status` after the person finishes. `wait_for_signature` is a short status check, not a wait for the entire human signing process.
7. Present `signed_pdf_url` only when the returned status confirms `completed`. Avoid requesting base64 by default. Never claim a pending request is signed.
8. Call `cancel_request` when the user asks to cancel. Describe cancelled, declined, or expired requests accurately without claiming successful signing. Ask whether the user wants a new request when appropriate.
9. Use `apply_signature_response` only for an actual human-produced response supplied through the supported workflow.
10. Do not use `sign_in_chat`, `apply_signature`, or `sign_with_typed_name` to manufacture consent. Card preview retrieval is app-only and is not part of the assistant's workflow.
11. Send feedback only when the user explicitly asks for it.
