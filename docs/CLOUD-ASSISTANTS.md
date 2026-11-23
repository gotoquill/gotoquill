# Connecting a remote assistant to Local

Local can expose Streamable HTTP with `gotoquill mcp --http`, or use `gotoquill tunnel` for a temporary HTTPS endpoint. Use the endpoint and pairing flow shown by your local CLI. Never paste pairing codes into issues or logs. Keep the machine awake while requests are pending.

For sealed-link transport in this mode, configure your own [relay](../relay/README.md) with `GOTOQUILL_RELAY_URL` and `GOTOQUILL_RELAY_TYPE=gotoquill`. Remote mode requires an explicit relay URL. The relay receives ciphertext; Local retains document processing and keys on your machine. Keep signing links private and obtain human UI consent.

Gotoquill Cloud is a separate hosted service at `https://mcp.gotoquill.com/mcp`. Its implementation is private. Cloud stores pending documents and signing keys and is not end-to-end encrypted or zero-knowledge. Current host setup guides are at [Support](https://gotoquill.com/support/). Connecting or changing destinations does not migrate pending requests, PDFs or keys.
