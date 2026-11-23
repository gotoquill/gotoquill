# Gotoquill

Request a real human signature on a PDF through the Gotoquill MCP tools.
Pass PDF bytes or a reachable PDF URL to the remote server; it cannot read local
paths. Present the returned sign_url so the human can review, sign and consent.
Check the returned request_id with get_signature_status or wait_for_signature;
provide the signed download only when status is completed. Never invent a
signature, consent, request ID or completed result. Form filling is out of scope.
