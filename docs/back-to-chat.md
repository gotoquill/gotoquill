# After signing: why there is no "Back to chat" button

The signed result reaches the agent automatically, so the signer only needs to leave the page.
The "Signed ✓" screen therefore shows just *"You can close this window and go back to the chat. Your signed document will be waiting for you there."*, plus a subtle
**Return to chat** text link when the request set a `return_to` deep link. There is no close button.

## Why a page cannot close the viewer

Browsers only let a page close a window that a script opened (`window.open`). When the signer opens
the page from a link or a chat attachment, `window.close()` is ignored:

| Context | Can the page close itself? | How the signer gets back |
|---|---|---|
| Desktop browser tab opened from a link | No | Close the tab |
| Popup opened with `window.open` | Yes | (not how chat apps open attachments) |
| iOS Safari / Quick Look file preview | No | The viewer's Done / X |
| Android Chrome / Custom Tab | No | System back / the X |
| In-app webview (WKWebView, Android WebView) | Only if the app implements it | The app's close control |
| Iframe / embedded view in the chat | No (the host owns it) | The host's UI |

In real use, an earlier version that tried `window.close()`, `postMessage` to the parent/opener and
`history.back()` continued the chat, but the attachment viewer stayed open. A plain message is honest
and works everywhere.

## What a host chat app would need for a real close

- Embedded views: listen for a message from the page and dismiss the sheet (MCP Apps hosts already get
  `ui/message` from the in-chat view after signing).
- Native webviews: implement the close callback (`WKUIDelegate.webViewDidClose`,
  `WebChromeClient.onCloseWindow`) or open the page as a script popup.
- Deep links: pass `return_to` so the **Return to chat** link jumps into the chat app.
