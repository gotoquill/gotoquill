# Gotoquill for Rakazo

This plugin connects Rakazo to Gotoquill for human signatures on PDFs and includes a signing workflow skill. It uses Agent Plugins 1.1.0 manifests, checked against the [Rakazo plugin guide](https://rakazo.com/docs/build-a-plugin/) and its MCP server example at source commit `e30b6a663e99447a914ab7ff5d82d5df706022e5`.

The public plugin folder is:

```text
https://github.com/gotoquill/gotoquill/tree/main/integrations/rakazo
```

This folder is not listed in the Rakazo marketplace yet, and Gotoquill has not been tested inside Rakazo.

## Connection and signing

The Streamable HTTP MCP URL is `https://mcp.gotoquill.com/mcp`.

OAuth is discovered from the server. In **Integrations**, users choose **Sign in** or **Connect OAuth** and authorize in the browser. No credentials, tokens, or OAuth client settings are stored in these files. Never supply credentials in chat.

Request a signature, open the returned `sign_url`, then review, sign, and consent in the browser. A card may appear, but hosts without card tool calls use **Open signing page** or the text link. After signing, check status and retrieve `signed_pdf_url` only when completed. See [Rakazo support](../../docs/Rakazo%20support.md) for connection and browser-signing guidance.

## Install from GitHub

In **Integrations**, choose **+** > **From GitHub**, paste the folder URL above, and choose **Preview**. Review servers, skills, and any skipped parts. Choose **Connect**, then **Add skills**, sign in, and select **Use in this bot**. Installs are pinned to the selected commit. Preview again if the source changes. Rakazo does not accept private repositories or local folders as install sources.

## Testing

Use your own account and the repository's `examples/sample_contract.pdf`. Verify OAuth, the browser signing link, explicit human consent, status checks, and completed-PDF retrieval. Check cancellation, expiry, popup blocking, and reconnecting. Do not include credentials in testing notes. Gotoquill has not been tested inside Rakazo yet.
