# Gotoquill

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Built by [Shay Levi](https://www.linkedin.com/in/shaylevi).

<!-- mcp-name: io.github.gotoquill/gotoquill -->

![gotoquill demo: an AI agent sends a lease, the signer signs on the phone](docs/assets/demo.gif)

Gotoquill lets AI assistants ask a person to sign a PDF, with explicit human consent in the signing UI. It supports ChatGPT, Claude, Gemini, Le Chat, Muse, and local MCP clients. Form filling is outside the project scope.

[Website](https://gotoquill.com/) · [Support](https://gotoquill.com/support/) · [Feedback](https://gotoquill.com/feedback/) · [Privacy](https://gotoquill.com/privacy/) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

## Quickstart

For hosted signing, connect your assistant to `https://mcp.gotoquill.com/mcp`. See the [setup guides](https://gotoquill.com/support/). Ask it to request your signature on a PDF, review the document, and confirm in the signing UI.

For your first Cloud chat, paste:

> Create a short sample NDA between my company and Dana Cohen, then let me sign it.

Run Local with `uvx gotoquill mcp`. Source: [gotoquill/gotoquill](https://github.com/gotoquill/gotoquill). See the client configurations below. The following workflow describes local sealed-link signing.

The agent calls one tool with a PDF path and gets back a **link** (and a QR code).
You open it on your phone or any computer, see the document, draw or type your
signature, tick the consent box and press **Sign**. The page says
"Signed ✓ , you can close this page". The signed PDF and a proof record are
saved next to the original file, on the agent's computer.

- No account, no server of your own. The link is **end-to-end encrypted**: the secret key is in the
  part of the link after `#`, which browsers never send to any server.
- Other ways are still there: a local page on `127.0.0.1` / inside the chat (`delivery="page"`) and an
  offline file (`delivery="file"`).
- Output: `contract - signed.pdf` and `contract - signed.audit.json` (who, when, SHA-256 of both files).
- Auto-placement: signature form fields first, else labels such as *Signature*, *Sign here*, *חתימת המבוטח*
  (also reversed RTL text), *Firma*, *Unterschrift*, *Assinatura*, *Podpis*, *Подпись*, *توقيع*, *署名*, next to
  the nearest empty drawn box or ruled line (left, right, above or below). All detected spots are signed unless
  you pass `spots` (`"first"`, `"last"`, `[1, 3]`). With `add_date`, matching *Date* / *תאריך* boxes or fields
  get the signing date. Scanned PDFs with no text fall back to the bottom-right of the last page and the result
  says it is a guess (`placement_info.guess`).
- Preview: `request_signature` returns `placements` and `preview_png_path` (the page with the spots
  highlighted). Show it to the user first. The signing page highlights the same spots.
- When it is signed, `get_signature_status` returns `signed_pdf_path`, a small `signed_preview_png_path` and a
  `next` hint. **Agents should send the signed PDF back to the signer in the chat right away, without being
  asked.**

## Install

Python 3.10 or later and [uv](https://docs.astral.sh/uv/) are required:

```bash
uvx gotoquill mcp
```

For a persistent executable (including self-hosted Rakazo), use `uv tool install gotoquill`,
then `gotoquill mcp`. Use an absolute executable path if your host does not inherit your PATH.
Developers can clone [the source](https://github.com/gotoquill/gotoquill) and install with
`python -m pip install -e '.[dev]'` in a virtual environment.

Choose Cloud or Local and follow Choose / Connect / Verify / Switch at the
[connection chooser](https://gotoquill.com/#connect). Connect and verify the
destination before retiring the previous connection after pending work finishes.
Switching changes where new requests are created, without moving PDFs or requests.

## Add it to your agent

**Claude Desktop**: in Settings → Developer → Edit Config (`claude_desktop_config.json`):
```json
{"mcpServers": {"gotoquill": {"command": "uvx", "args": ["gotoquill", "mcp"]}}}
```

**Claude Code**:
```bash
claude mcp add gotoquill -- uvx gotoquill mcp
```

**Cursor**: `~/.cursor/mcp.json` (or `.cursor/mcp.json` in a project):
```json
{"mcpServers": {"gotoquill": {"command": "uvx", "args": ["gotoquill", "mcp"]}}}
```

**VS Code (Copilot)**:
```bash
code --add-mcp '{"name":"gotoquill","command":"uvx","args":["gotoquill","mcp"]}'
```

**Goose**:
```bash
goose session --with-extension "uvx gotoquill mcp"
```
(or add it for good with `goose configure` → Add Extension → Command-line Extension, using the same command)

**Codex CLI / ChatGPT desktop (Codex)**:
```bash
codex mcp add gotoquill -- uvx gotoquill mcp
```

**Gemini CLI**:
```bash
gemini mcp add --trust --timeout 900000 gotoquill gotoquill mcp
```
Use `--trust` (or `"trust": true` on the server in `.gemini/settings.json`). Without it, headless `gemini -p` runs wait forever for a tool confirmation (gemini-cli #11459). The long `timeout` covers `wait_for_signature`.

**LangChain / LangGraph (Python and TypeScript)**: follow the runnable
[Python example](examples/langchain-python/README.md) or
[TypeScript example](examples/langchain-typescript/README.md). Both support an
installed Local executable or Cloud OAuth by changing one connection block.
They use the current official adapters and the shared unpublished helpers.
Present the browser signing link and wait for human UI consent; there is no
in-chat signing card in these integrations.

Not using MCP? See "Plain function calling" below.

Then just ask: *"Get my signature on ~/Downloads/contract.pdf."*

## Tools

| Tool | What it does |
| --- | --- |
| `request_signature(pdf_path, ...)` | Returns `request_id`, `sign_url`, `qr_png_path`, `qr_ascii`, `output_path`. Options: `delivery` (`"link"` default, `"page"`, `"file"`), `output_path`, `signer_name`, `message`, `add_date`, `placements`, `expires_in_minutes`, `open_browser`, `return_to` (Back-to-chat target, see below), `wait_seconds` (default 0; block until final, max 600). |
| `get_signature_status(request_id, wait_seconds=0)` | `pending`, `completed`, `declined`, `expired` or `cancelled`. When completed it gives `output_path`/`signed_pdf_path`, `audit_path`, `signed_preview_png_path` and `next` (send the signed PDF back to the signer in chat right away, unasked). Use `wait_seconds` (up to 600) to wait for the human. For links, this is when the reply is fetched and the PDF is signed. |
| `wait_for_signature(request_id, wait_seconds=600)` | Same result as `get_signature_status`, waiting by default. Call it right after sending the link, in the same turn, and again while pending. In MCP it is async and sends progress notifications, so the server stays responsive. |
| `connect_notifications(...)` | One-time setup: saves notify targets (OpenClaw, webhook, Telegram) that every later request uses automatically. `action="status"` / `"test"` / `"remove"`. See below. |
| `cancel_request(request_id)` | Cancels and closes the page. |
| `apply_signature_response(request_id, response_path or response_text)` | Finishes a `delivery="file"` request with the reply the signer sent back. |

Where the signature goes: if you don't pass `placements`, gotoquill looks for a
signature line or field ("Signature", "Sign here", a PDF signature field) and
puts it there. Otherwise it goes at the bottom of the last page.


## Getting told when it's signed

Agents only act on their own turns. If the agent sends the link and ends its turn, nobody tells it when the
human signs on their phone. gotoquill makes sure something wakes the agent:

1. **`gotoquill wait <request_id> [--timeout SECONDS]`** blocks until the request is final, pulls the encrypted
   reply, stamps the PDF, prints the final status JSON (with `signed_pdf_path` and `next`) and exits with:

   | exit | meaning |
   |---|---|
   | 0 | completed (signed) |
   | 3 | declined |
   | 4 | expired |
   | 5 | cancelled |
   | 6 | `--timeout` passed, still pending (run it again) |
   | 2 | error (e.g. unknown request id) |

   Default timeout: until the request expires. Run it as a **background job** in agents whose host notifies them
   when a background command finishes (e.g. coding agents with background shells).
2. **Completion hooks** on `request_signature` (MCP, `gotoquill.tools`, CLI `sign --on-complete-command/--on-complete-webhook`):
   - `on_complete_command`: shell command; status JSON on stdin; env `GOTOQUILL_STATUS`, `GOTOQUILL_SIGNED_PDF`,
     `GOTOQUILL_REQUEST_ID`, `GOTOQUILL_PREVIEW_PNG`, `GOTOQUILL_AUDIT`, `GOTOQUILL_NEXT`.
   - `on_complete_webhook`: the status JSON is POSTed to this URL (headers `X-Gotoquill-Request`, `X-Gotoquill-Status`,
     plus the HMAC headers below). Optional `webhook_headers` (CLI `--webhook-header K=V`, `K=env:VAR`) and
     `webhook_body` (a JSON body template, CLI `--webhook-body '{...}'`).
   Hooks fire **exactly once** (an atomic marker file guards them across processes), from whichever process sees
   the final status first. A **watcher** keeps polling the relay even if the agent forgets: a detached process
   for the CLI / Python tools (it survives the call returning), a task inside the long-lived MCP server. The
   watcher stamps the signed PDF before firing, so `GOTOQUILL_SIGNED_PDF` is ready. Results are in
   `~/.config/gotoquill/notify/<request_id>/hook-result.json` (config dir).
3. **MCP notifications.** The MCP server watches every link/page request. When it finishes, it sends
   `notifications/resources/updated` for the resource `gotoquill://requests/<request_id>` (readable: the status
   JSON) and a `notice` log message. While `get_signature_status` waits it sends progress and log notifications.

### One-time setup: `gotoquill connect`

Run once (by the agent itself: CLI `gotoquill connect` or MCP `connect_notifications`). It saves **notify
targets**, and from then on every `request_signature` without its own hooks uses them automatically, so a
finished signature wakes the agent with no copy/paste by the human.

```bash
gotoquill connect                                   # auto-detects OpenClaw; shows a plan, then:
gotoquill connect --yes                             # applies it (backs up openclaw.json first)
gotoquill connect --webhook https://n8n.example/webhook/sign --header-env Authorization=GOTOQUILL_WAKE_AUTH
gotoquill connect --telegram-bot-token-env TELEGRAM_BOT_TOKEN --chat-id 123456789
gotoquill connect --status                          # targets, secrets masked
gotoquill connect --test                            # ping every target
gotoquill connect --remove [ID]                     # remove one target, or all
```

- **OpenClaw** (detected via `~/.openclaw/openclaw.json`, `OPENCLAW_CONFIG_PATH`, `OPENCLAW_STATE_DIR`): sets
  `hooks.enabled`, a `hooks.token` (keeps an existing one) and puts a mapping `gotoquill` first
  (`match.path: "gotoquill"`, `action: "wake"`, `textTemplate: "{{message}}"`), then posts to
  `http://127.0.0.1:<gateway port>/hooks/gotoquill` with `Authorization: Bearer <token>`. The gateway hot-reloads
  config. `--openclaw-action agent [--openclaw-agent ID]` runs an isolated agent turn (session `hook:gotoquill`,
  reply to the last channel) instead of waking the main session. An existing config is never changed without
  `--yes` (MCP `yes=true`): without it you get a masked diff and exit code 1. The original is saved as
  `openclaw.json.gotoquill-backup-<time>` (mode 0600). JSON5 files with comments are not edited; you get the
  snippet to paste instead. Symlinked configs are refused.
- **Webhook** (n8n, Zapier, Make, a LangGraph/your own server): `--header K=V` or `--header-env K=ENVVAR`
  (`env:VAR` values are read from the environment when the hook fires, so the secret never sits in gotoquill's
  files); `--body-template '{"text": "{{message}}"}'`.
- **Telegram**: `sendMessage` to `--chat-id`, bot token read from the env var named by `--telegram-bot-token-env`
  at send time. Note: bots never see their own messages, so this tells the human (and any agent reading that
  chat through another account), not a bot-based agent itself.

Every POST is signed: `X-Gotoquill-Timestamp: <unix>` and `X-Gotoquill-Signature: sha256=<hex>` =
HMAC-SHA256(secret, `<timestamp>.<raw body>`). The secret (`secrets.token_urlsafe(32)`) and targets live in
`<config dir>/notify-targets.json`, encrypted with a key in the OS keychain (or a 0600 file without a
keychain). Verify in Python with `gotoquill.targets.verify(body, ts, sig, secret)`.

Body template placeholders: `{{request_id}}`, `{{status}}`, `{{document_name}}`, `{{signed_pdf_path}}`,
`{{audit_path}}`, `{{next}}`, `{{message}}` (a ready "Document … was signed …" sentence), and the whole value
`"{{status_json}}"` for the status object. Default: the status JSON. Exit codes: 0 ok, 1 needs `--yes`,
3 a target or test failed, 2 error. Secrets are never printed.

What the agent must do (also in `next`, the MCP instructions and tool descriptions): right after
`request_signature`, **immediately** start waiting in a way that will wake it, and never end its turn assuming it
will be told:
(a) if it can run background shell jobs that notify on exit, run `gotoquill wait <request_id>` in the background;
(b) otherwise call `wait_for_signature(request_id)` (= `get_signature_status(request_id, wait_seconds=600)`) again and
again in the same turn;
(c) or use the hooks. When it is completed, send the signed PDF back to the signer in the chat right away.

## Optional “Signed by” line

The signing sheet has an optional checkbox, off by default: *Add “Signed by {name} · {date}” under my signature*. When the signer ticks it, the reply carries `signed_by_line: true` and the signed PDF gets one small grey line under each signature spot. Left unticked, nothing extra is added.

### Back to chat (the signer's side)

No chat host wakes the model on its own, so gotoquill also makes it one tap for the human to tell the agent:

- **In-chat view (MCP Apps hosts that support `ui/message`):** after Sign, the view posts
  *"I signed <document> ✅ Please send me the signed file."* into the chat as a user message (and, if supported,
  `ui/update-model-context` with the request id), so the conversation continues by itself. If the host supports
  neither, the view shows the signed message instead.
- **Every browser page** (sealed link, link-file, offline file, local page) ends on a clean "Signed ✓" screen with
  *"You can close this window and go back to the chat. Your signed document will be waiting for you there."* There is no close button: a page cannot close the chat app's viewer
  (see [docs/back-to-chat.md](docs/back-to-chat.md)). Pass `return_to` to add a subtle **Return to chat** text link,
  pre-filled with "I signed … ✅":

  | `return_to` | opens |
  |---|---|
  | `whatsapp` / `whatsapp:+15550102000` | `https://wa.me/[number]?text=…` |
  | `telegram` / `telegram:@your_bot` | `https://t.me/your_bot?text=…` |
  | `sms` / `sms:+15550102000` | `sms:[number]?&body=…` |
  | `https://…{text}…` or an app link (`slack:`, `discord:`, `tg:`, `msteams:`, `sgnl:`, `mailto:` …) | your link, with `{text}` replaced |

  Only allow-listed schemes are accepted (no `javascript:`, `data:`, `file:` or `http:`), and the value is checked
  again in the page. For sealed links it travels **inside the encrypted request**, not in the URL. Without
  `return_to` there is no link, only the message. In the offline file the pre-filled reply carries the signature code
  when it is short enough; otherwise the human sends the reply file first.

  CLI: `gotoquill sign contract.pdf --return-to whatsapp:+15550102000`.

## Sealed link (the default)

How it works, in simple words:

1. gotoquill makes a fresh secret key, and locks (encrypts) the page pictures, the PDF and the request
   details with it (AES-256-GCM).
2. It drops the locked box at a public mailbox , [ntfy.sh](https://ntfy.sh) by default (free, no account),
   or the open-source [gotoquill relay](relay/README.md) (`GOTOQUILL_RELAY_TYPE=gotoquill`) for hosts that
   block ntfy , under a random 43-character name. A second random name is for the answer. There is **no
   shared public gotoquill relay**: each user deploys on **their own Cloudflare account** (free, one
   command , see [`relay/README.md`](relay/README.md)).
3. You get a link like `https://example.github.io/gotoquill/#v=1&q=…&a=…&k=…`. The part after `#`
   (mailbox names and key) never leaves your browser. The page removes it from the address bar right away.
4. The page downloads the locked box, unlocks it in your browser, shows the document, and when you sign
   it locks your answer with the same key and drops it in the answer mailbox.
5. `get_signature_status` picks up the answer, unlocks it, checks request id, document SHA-256, an HMAC
   proof, expiry and one-time use, and stamps the PDF (pypdf + reportlab). The audit says
   `"delivery": "sealed link via relay"`.

ntfy.sh (and the gotoquill relay) only ever see scrambled bytes (checked in `examples/e2e_sealed.py`).
Links expire after 60 minutes by default (ntfy max 180; gotoquill relay default TTL **1h**, max
**24h**, body max **~1 MiB**, per-IP rate limit). After signing, the key is deleted from the agent's
records too. If the agent's app supports MCP URL elicitation, it is asked to offer the link to you
directly; otherwise the link comes back as text (with `qr_png_path` and `qr_ascii` for a QR code).

Settings: `GOTOQUILL_RELAY_URL` / `GOTOQUILL_RELAY` (ntfy base **or your** gotoquill Worker URL ,
**required** when using gotoquill / cloud mode), `GOTOQUILL_RELAY_TYPE` (`ntfy` or `gotoquill`),
`GOTOQUILL_CLOUD=1` (prefers gotoquill; still needs your URL , see [`relay/README.md`](relay/README.md)),
and `GOTOQUILL_PAGE_BASE` (where the signing page is hosted; `GOTOQUILL_PAGE_URL` also works). If that page isn't reachable (checked with a
3 s request, cached for 10 min), gotoquill falls back to the self-contained `sign.html` file and returns
`html_path` instead of a link. Command line: `gotoquill sign contract.pdf --link` prints the QR + link and waits.

### Hosting the signing page

The page is the `web/` folder: `index.html` + `sign.js`. Plain static files, no build step, nothing
loaded from other sites. Put it on any static host with **https** (the browser crypto needs it) and set
`GOTOQUILL_PAGE_BASE` to its address.

- **GitHub Pages**: Settings → Pages → deploy from branch, folder `/web` (or copy `web/` to a `gh-pages`
  branch). Note: GitHub Pages is free only for **public** repos; private repos need a paid plan
  (Pro/Team/Enterprise). The default `https://example.github.io/gotoquill/` is a placeholder until it is
  published there.
- Netlify, Cloudflare Pages, any web server: upload `web/` as is.
- For a quick local test: `python -m http.server -d web 8000 --bind 127.0.0.1` and
  `GOTOQUILL_PAGE_URL=http://127.0.0.1:8000/` (only works on that computer).

The page host never sees your document or signature: it only serves the same two files to everyone.

## On this computer (`delivery="page"`)

A signing page opens in your browser on `127.0.0.1`. If the browser can't be opened (for example over
SSH), the agent gets the `sign_url` and can show it to you.

## In-chat signing (MCP Apps)

gotoquill supports [MCP Apps](https://modelcontextprotocol.io/docs/extensions/apps)
(spec 2026-01-26). `request_signature` points to the UI resource
`ui://gotoquill/sign.html`. If your app says it supports MCP Apps, the signing
page shows up inside the chat and no browser tab opens. The page has an
"Open in browser instead" link. Apps without MCP Apps support just get the
browser page, so nothing changes for them. This needs `delivery="page"`; with the default link mode
the in-chat view just shows the link.

## Saved signature (optional)

Tired of drawing your signature every time? Tick **"Save this signature on this computer for next time"** on the
signing page (it is off by default). You can save a full signature and, separately, your initials.

Next time, the page shows your saved signature with a **Use saved signature** button. You still have to tick the
consent box and click **Sign and approve** yourself. Works the same in the browser page and in the in-chat view.

**Your agent can never use it on its own.** No tool ever returns the signature picture to the agent, and the
saved signature can only be applied by a click on the signing page (the page gets a one-time unlock code that
the agent never sees). The audit record says whether you used a `"saved signature reused"` or a
`"newly drawn"` / `"newly typed"` one.

**Where it is stored:** only on this computer, in `signatures.json` in your config folder
(`~/.config/gotoquill/` on Linux, `~/Library/Application Support/gotoquill/` on macOS,
`%LOCALAPPDATA%\gotoquill\` on Windows). The file is readable only by you (permissions `0600`).

* If your computer has a keychain (macOS Keychain, Windows Credential Manager, or a Linux Secret Service such as
  GNOME Keyring / KWallet), the file is **encrypted**, and the key lives in the keychain.
* If not (for example a headless Linux server), the file is a **plain local file** - not encrypted, protected
  only by file permissions. `gotoquill signature show` tells you which one you have.
  (Set `GOTOQUILL_NO_KEYRING=1` to force the plain file; `GOTOQUILL_CONFIG_DIR` to move the folder.)

Remove it any time with the **Delete** link on the signing page, or:

```bash
gotoquill signature show      # path, encrypted or not, names and dates - never the picture
gotoquill signature delete    # delete all  (--name initials to delete one)
```

Honest limits: this keeps the signature away from the agent's *tools*. A program running as you with full access
to your files (and your unlocked keychain) could still read it, just like any other file you own. Also, the
signed PDF itself of course contains the signature image.

## Cloudflare tunnel phone link (deprecated)

Use the sealed link instead. This older option still works for now:

Normally the signing page lives on `127.0.0.1`, so only the computer running the agent can open it.
If your agent runs somewhere else (for example a cloud assistant's computer) and you are on your phone,
turn on **phone link**:

- MCP / Python: `request_signature(pdf_path=..., share_link=true)`
- Command line: `gotoquill sign contract.pdf --share-link`
- Or always on: `GOTOQUILL_SHARE_LINK=1`

What happens:

1. gotoquill starts a free, temporary [Cloudflare quick tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/)
   (`cloudflared`, no account needed) to that one signing page.
2. You get a link like `https://some-random-words.trycloudflare.com/s/<one-time-token>` as `sign_url`
   (the local address is still in `local_url`). Open it on any phone or browser and sign.
3. When you sign, decline, cancel, or the link expires, the tunnel is shut down.

Safety rules for phone links:

- The link works for **that one request only** (the page accepts only `localhost` or that exact tunnel name).
- It expires sooner: **15 minutes** by default (`GOTOQUILL_SHARE_TTL_MINUTES`, or `expires_in_minutes`).
- It is one-time, and it locks after too many wrong guesses or failed submits.
- The audit record says `"delivery": "share link via tunnel"`.

Privacy: the page and your signature travel through Cloudflare's network, encrypted with HTTPS.
Nothing is stored at Cloudflare or anywhere else online; the signed PDF is written only on the agent's computer.

`cloudflared` is used from your `PATH` (or `GOTOQUILL_CLOUDFLARED=/path/to/cloudflared`). If it is missing,
gotoquill downloads it once from the official GitHub release (`github.com/cloudflare/cloudflared`) into your
cache folder (`~/.cache/gotoquill/bin`, `~/Library/Caches/gotoquill/bin`, or `%LOCALAPPDATA%\gotoquill\bin`)
and checks its SHA-256 against the release before running it. Works on Linux, macOS and Windows.
The tunnel needs outbound port 7844 (UDP, or TCP with `GOTOQUILL_TUNNEL_PROTOCOL=http2`) to Cloudflare.
If the tunnel cannot start (no internet, firewall), you get a clear error and nothing is shared;
sign on the agent's computer instead, or install `cloudflared` yourself.

## No connection? Sign with a file

Sometimes the agent and you can't reach each other at all. For example the
agent runs in the cloud and you are on your Android phone. Then use file mode:

1. The agent calls `request_signature(pdf_path, delivery="file")`. It writes
   one file, like `Contract - sign.html`, and sends it to you in the chat.
2. You open it on any phone or computer (Downloads, Files app, any browser).
   It works offline: the pages are inside the file and it never connects to
   anything. You see the document with blue "Sign here" boxes, draw or type
   your signature, tick the consent box and tap **Sign and approve**.
3. The page makes a compact response code (`GOTOQUILL1…`). Tap **Copy
   response code** and paste it back into the same chat that sent the HTML
   (closing the tab does nothing by itself). On Android/iOS you can also tap
   **Share reply file** to use the system share sheet. **Save reply file**
   stays under "Other ways to send it back".
4. The agent calls `apply_signature_response(request_id, response_text=...)`
   with the pasted code (or `response_path=` for the `.gotoquill` file). The
   signed PDF and audit JSON are written; the audit says
   `"delivery": "file via chat"`.

Safety: the reply only works for that one request and that exact document
(request id, document SHA-256 and an HMAC proof made with a key that is only
in that HTML file). It works once, and the request expires (7 days by
default, `expires_in_minutes` to change). Pending requests are kept in the
config folder (`file-requests/`), so they survive restarts. Treat the HTML
file like a one-time link: whoever has it can sign that one request.

## Command line

```bash
gotoquill sign contract.pdf --link          # sealed link + QR code in the terminal, waits
gotoquill sign contract.pdf                 # opens the browser, waits, prints JSON
gotoquill sign contract.pdf -o out.pdf --signer-name "Dana" --add-date
gotoquill sign contract.pdf --no-browser    # just print the link
gotoquill sign contract.pdf --file-mode     # no connection: write "Contract - sign.html"
gotoquill apply req_123 "Contract - signature.gotoquill"   # or paste the GOTOQUILL1 code
gotoquill sign contract.pdf --link --no-wait --on-complete-command 'notify-send "$GOTOQUILL_STATUS"'
gotoquill wait req_123 --timeout 3600       # blocks; exit 0 signed, 3 declined, 4 expired, 5 cancelled, 6 timeout
gotoquill mcp                               # run the MCP server (stdio); also the default
gotoquill mcp --http --port 8787            # Streamable HTTP at /mcp (for cloud assistants)
gotoquill tunnel                            # HTTP MCP + Cloudflare quick tunnel; print public URL
```

### Cloud assistants (ChatGPT / Claude / Muse)

Desktop hosts use stdio. For **ChatGPT custom MCP (Dots)**, **Claude.ai / Cowork / Duet
custom connectors**, and **Meta Muse**, run a tunnel so the vendor’s cloud can reach
your laptop:

```bash
gotoquill tunnel    # prints https://….trycloudflare.com/mcp + a one-time pairing code
```

Paste that URL as a custom connector (OAuth). Details, auth per host, PDF in/out, and a
phone/laptop checklist: **[docs/CLOUD-ASSISTANTS.md](docs/CLOUD-ASSISTANTS.md)**.

## Python

```python
from gotoquill import sign_pdf
result = sign_pdf("contract.pdf", signer_name="Dana")   # blocks until signed/declined/expired
print(result["status"], result.get("output_path"))
```

## Plain function calling

`schemas/functions.json` holds the three tool schemas in OpenAI/JSON-Schema format.
Give them to any model and send its calls to:

```python
from gotoquill import tools
tools.FUNCTIONS                       # the schemas
tools.call(name, arguments)           # run a tool call (arguments: dict or JSON string)
```

## Settings (env vars, all optional)

| Var | Default | |
| --- | --- | --- |
| `GOTOQUILL_DATA_DIR` | `~/.gotoquill` | where request records are kept |
| `GOTOQUILL_OPEN_BROWSER` | `1` | set `0` to never open a browser |
| `GOTOQUILL_TTL_MINUTES` | `30` | how long a link stays valid |
| `GOTOQUILL_MAX_PDF_MB` | `50` | max PDF size |
| `GOTOQUILL_RELAY_URL` (alias `GOTOQUILL_RELAY`) | `https://ntfy.sh` | ntfy base, **or your** gotoquill Worker (required for gotoquill/cloud) |
| `GOTOQUILL_RELAY_TYPE` | auto (`ntfy`) | `ntfy` or `gotoquill` (see [`relay/README.md`](relay/README.md)) |
| `GOTOQUILL_CLOUD` | unset | `1` prefers gotoquill (set by `mcp --http` / `tunnel`); needs your `GOTOQUILL_RELAY_URL` |
| `GOTOQUILL_PAGE_BASE` (alias `GOTOQUILL_PAGE_URL`) | `https://example.github.io/gotoquill/` | where `web/` is hosted; if unreachable, links fall back to `sign.html` |
| `GOTOQUILL_PAGE_CHECK` | `1` | `0` skips the reachability check |

## Security notes

- Sealed links: AES-256-GCM, key only in the link's `#` part; the relay stores ciphertext only; the reply
  must decrypt with the key, match the request id and document hash, and carry a valid HMAC proof; one use.
  Treat the link like a one-time password: whoever has it can sign that one request.
- The local page only listens on `127.0.0.1` and refuses other Host headers.
- Each link has a random token, works once and expires.
- The proof record has SHA-256 hashes of the original and signed PDF, plus the time and name.
  This is a simple e-signature, not a certificate-based digital signature. See [Disclaimer](#disclaimer).

## Develop

```bash
uv venv && . .venv/bin/activate && uv pip install -e '.[dev]'
pytest -q
python examples/e2e_demo.py /tmp/demo   # real stdio MCP client + headless Chrome, both paths
python examples/e2e_sealed.py /tmp/demo # web/ on 127.0.0.1 + REAL ntfy.sh + phone-size Chrome
```

See [License](#license).

### Sealed file (`delivery='link-file'`, CLI `--link-file`)

Same encrypted relay flow as the sealed link, but nothing to host: one self-contained `<name> - sign.html`
(the `web/` page with its script inlined and the relay/topics/key embedded inside the file) to send in the chat.
The signer opens it in a browser with internet; it fetches the encrypted document from ntfy.sh and posts the
encrypted reply back (ntfy.sh answers `Access-Control-Allow-Origin: *`, so it works from `file://`, origin `null`).
The file holds the key: send it only to the signer. Check with `gotoquill status <id> --wait 60`.
Real e2e from `file://`: `python examples/e2e_sealed_file.py /tmp/demo`.

## Support the project

gotoquill is free and open source. If it saves you time, please consider supporting it:

- Star the repo and tell people about it
- Report bugs and send pull requests (see [CONTRIBUTING.md](CONTRIBUTING.md))

## Sponsors

Thank you to everyone who supports gotoquill. Companies interested in sponsoring or partnering can reach
out to [@shay2301](https://github.com/shay2301).

<!-- sponsors --><!-- sponsors -->

## Contributing

Contributions and issue reports are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md). The [Contributor License Agreement](CLA.md) is approved but not yet in force. Signing is inactive and requires a separate maintainer decision.

## Disclaimer

gotoquill is provided **as is, without warranty of any kind**, and it is **not legal advice**. It creates a
simple electronic signature with an audit record. It is not a certified or qualified e-signature or trust
service (for example, not an eIDAS QES), and there is no guarantee that it meets ESIGN, UETA or any other law.
You are solely responsible for:
- legal validity where you are;
- signer consent and identity verification;
- record retention;
- data protection;
- security.

The authors are not liable for lost or altered documents, misuse or any damages. Third-party services, such
as the ntfy.sh relay, are outside the author's control. Support is best-effort. The hosted Gotoquill Cloud
service has its own [Terms of Service](https://gotoquill.com/terms/) and [Privacy Policy](https://gotoquill.com/privacy/). Full text:
[DISCLAIMER.md](DISCLAIMER.md).

## License

Copyright 2026 Shay Levi. Licensed under the [Apache License, Version 2.0](LICENSE); see also [NOTICE](NOTICE).
Third-party code (vendored @noble/ciphers, MIT) is listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

**Third-party licenses:** all runtime dependencies are permissive (permissive (MIT, BSD, Apache-2.0 and similar; full list in THIRD_PARTY_NOTICES.md)). PDF work
uses pdfplumber (MIT), pypdf (BSD-3-Clause), reportlab (BSD-3-Clause) and pypdfium2 (Apache-2.0 / BSD-3-Clause).
There are no AGPL or GPL dependencies. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the full list.

Created by [Shay Levi](https://github.com/shay2301).

## Licensing FAQ

- **Can I use Local commercially or self-host it?** Yes. Local code is Apache 2.0, including commercial use, modification and self-hosting, subject to the [license](LICENSE) and required notices.
- **What about Cloud?** Gotoquill Cloud is the separate hosted service intended for paid plans. Charging is not implemented in this change; current service terms still apply. Its implementation is not included in the public tree.
- **Can released versions lose Apache 2.0?** Released Apache versions stay Apache. The approved [CLA](CLA.md) describes additional rights for the owner without withdrawing those releases.
- **Can my fork use the Gotoquill name?** Apache 2.0 does not grant trademark rights. See the approved [trademark policy](TRADEMARK.md) for naming and truthful attribution.

The CLA, trademark policy and Cloud data-handling texts were approved by Shay Levi on 23 November 2026 (Asia/Jerusalem). CLA signing remains inactive. This FAQ is not legal advice.
