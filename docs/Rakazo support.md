# Rakazo support

The [Rakazo integration](../integrations/rakazo/README.md) is an unpublished plugin draft. In Rakazo, add `https://mcp.gotoquill.com/mcp` as a Streamable HTTP MCP server, then complete OAuth in the browser. Do not provide credentials in chat. Real-account compatibility still needs verification.

Request a signature, open the returned `sign_url`, review the PDF and explicitly consent in the signing UI. If the host cannot call tools from a card, use the browser link. Ask the assistant to check status after signing and retrieve the signed file only when status is `completed`. Reconnect if authorization expires. Current hosted setup information is at [Support](https://gotoquill.com/support/).
