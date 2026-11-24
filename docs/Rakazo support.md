# Rakazo support

The [Rakazo integration](../integrations/rakazo/README.md) is the public plugin folder for connecting Rakazo to Gotoquill. It is not listed in the Rakazo marketplace yet, and it has not been tested inside Rakazo. In Rakazo, add `https://mcp.gotoquill.com/mcp` as a Streamable HTTP MCP server, or install the plugin from GitHub, then complete OAuth in the browser. Do not provide credentials in chat.

Request a signature, open the returned `sign_url`, review the PDF and explicitly consent in the signing UI. If the host cannot call tools from a card, use the browser link. Ask the assistant to check status after signing and retrieve the signed file only when status is `completed`. Reconnect if authorization expires. Current hosted setup information is at [Support](https://gotoquill.com/support/).
