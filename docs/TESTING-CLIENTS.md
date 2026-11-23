# Testing gotoquill with real agent clients

gotoquill is an MCP server. Its unit tests (`.venv/bin/python -m pytest -q`) drive it in-process. This page covers
the **opt-in** end-to-end matrix. It checks that real agent clients, driven by a model, can:

1. discover the tools,
2. request a signature on `examples/sample_contract.pdf`,
3. wait for it, and
4. report the signed PDF path.

The matrix is not part of the default pytest run.

## Automated matrix (free clients, local model)

| client | how it is driven | config the harness writes (temp) |
|---|---|---|
| direct (control) | `tests/clients/direct_mcp_client.py`, a plain MCP stdio client with no model | - |
| Goose | `goose run --no-session --no-profile --provider ollama --with-extension "<env> uvx …" -t <prompt>` | GOOSE env only |
| OpenClaw | `openclaw mcp add gotoquill …`, `openclaw mcp doctor --probe`, then `openclaw agent exec --model ollama/<m>` | `OPENCLAW_STATE_DIR`, `OPENCLAW_CONFIG_PATH` |
| Hermes Agent | `hermes chat -Q --yolo -q <prompt>` | `HERMES_HOME/config.yaml` (`mcp_servers`, custom provider → Ollama `/v1`) |
| Gemini CLI (optional) | `gemini --yolo -p <prompt>` | `.gemini/settings.json` `mcpServers` |

Gemini CLI only runs when `GEMINI_API_KEY` is set; otherwise it is reported as `skipped`.
The harness writes `"trust": true` and `"timeout": 900000` on the gotoquill server, and sets `GEMINI_CLI_TRUST_WORKSPACE=true`. Without `trust`, non-interactive runs block on tool confirmation (gemini-cli #11459 / PR #14702). Gemini CLI users should set `trust: true` too.

`--provider gemini` points goose (`google`), OpenClaw (`google/<model>`) and Hermes (built-in `gemini` provider) at the Gemini API. The key is read from `GEMINI_API_KEY` in the env only and never written to disk. gemini-2.5-flash is closed to new keys, so use a current flash model. The free tier allows about 20 requests per model per day, which is less than one full 4-client × 2 run.

Every client gets the same prompt and the same server command, `uvx --from <repo> gotoquill mcp`.

Each attempt is isolated:

- a temp copy of the sample PDF
- its own `GOTOQUILL_DATA_DIR`, `GOTOQUILL_CONFIG_DIR` and `GOTOQUILL_CACHE_DIR`, plus `GOTOQUILL_NO_KEYRING=1`
- its own client config/home

A sidecar watches for the signing URL. It gets the URL from:

- the server's `$BROWSER` hook, which is a capture script, or
- `state.json`, or
- the client log.

It then signs the real page with Playwright headless Chromium: typed name, consent, then submit.

### What "pass" means for an attempt

| check | how |
|---|---|
| tools discovered | the client listed/probed the gotoquill tools (doctor probe, tool calls, or log) |
| request made | a request id appeared and the page was served |
| signed | `<name> - signed.pdf` exists next to the copy |
| audit | `<…>.audit.json` exists |
| hashes | the sha256 of the original and the signed PDF equal `original_sha256` and `signed_sha256` in the audit |
| agent waited | the agent itself got `status=completed` back from `wait_for_signature`/`get_signature_status`. The server's own watcher stamps the PDF even when the agent never waits, so "signed" alone is not enough. |
| path reported | soft check: whether the final answer contains the signed path (exact, by file name, or not mentioned) |
| duration | wall time per attempt |

An attempt is `ok` when request, signed, audit, hashes and agent-waited all hold. Each client gets up to
`--retries` attempts (default 3). With `--all-attempts`, every attempt runs, which gives a pass rate.

### Run it

```bash
# 1. local model (CPU is fine)
curl -fsSL https://ollama.com/install.sh | sh
OLLAMA_CONTEXT_LENGTH=16384 OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve &   # default 4K ctx overflows OpenClaw
ollama pull qwen2.5:3b      # or llama3.2:3b / qwen3:4b

# 2. clients (official installers; all free)
curl -fsSL https://github.com/block/goose/releases/download/stable/download_cli.sh | CONFIGURE=false bash
npm install -g openclaw @google/gemini-cli        # OpenClaw needs Node >= 24
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# 3. sidecar browser
.venv/bin/python -m pip install playwright && .venv/bin/python -m playwright install chromium

# 4. matrix
GOTOQUILL_CLIENT_E2E=1 .venv/bin/python scripts/client_matrix.py --retries 3 --all-attempts
.venv/bin/python scripts/client_matrix.py --clients direct,goose --model llama3.2:3b
```

Results go to `client-matrix-out/results.md` and `results.json`, which are git-ignored. Per-attempt logs are
`client-matrix-out/<client>-attemptN.log`. Use `--keep` to keep the temp sandboxes.

The harness uses `uvx --from <local checkout>` to build local source, not a published PyPI package. The script clears uv's cached build of gotoquill (`uv cache clea gotoquill`) before it starts, so that `uvx`
runs your working tree.

Run the matrix locally when needed. The public tree includes a manually triggered Python CI workflow.

**If `ollama pull` fails behind a proxy** (for example "redirect target not allowed"), fetch the manifest and blobs
from `https://registry.ollama.ai/v2/library/<model>/manifests/<tag>` with curl. Check each blob's sha256, then place
them under `~/.ollama/models/{manifests,blobs}`.

### Known limits of small local models

- Ollama's default 4K context is too small: OpenClaw's first request alone is about 8.4K tokens, and it fails with
  "exceeds the available context size". Serve with `OLLAMA_CONTEXT_LENGTH=16384` or more.
- Hermes Agent refuses to run any model served with less than 64K context. The harness writes `context_length`
  and `ollama_num_ctx: 65536` to the Hermes config, which makes every CPU turn slow.
- OpenClaw strips `BROWSER` from a stdio server's env, so the harness wraps the server as `env BROWSER=… uvx …`.
- Hermes leaves an idle-exit gateway running. The harness kills any process whose environment points into the
  attempt's sandbox.

3-4B models on CPU are the weak link, not the MCP server. The typical failure: the model calls `request_signature`
and `wait_for_signature` *in parallel*, with a made-up `request_id` such as `<request_id>`. It gets a 404 and then
asks the user for the id.

What gotoquill does about it (server side):

- `sign_pdf(pdf_path=...)` does the whole job in one call: it opens the page and waits for the signature.
- `request_signature(delivery="page")` also waits (up to 120 s, `GOTOQUILL_PAGE_AUTOWAIT`) when the page opened,
  so a model that stops after one tool call still gets `status=completed` and `signed_pdf_path`.
- Tool descriptions are short, imperative and include a sample call; the long guide lives in `gotoquill://help`.
- Inputs are lenient: relative paths, `~`, `file://` URLs, a missing `.pdf`, `"600"` for numbers, `"true"` for
  booleans, JSON strings for lists, and `local`/`browser` for `delivery="page"`.
- A placeholder id (`<request_id>`, `$(result)`, empty) resolves to the latest request in the session, with a
  `note`. An unknown real-looking id gets `recent_request_ids` and a ready-to-run `next` call.
- Every result and error has `next`; pending results also have `next_call` (`{"tool", "arguments"}`).

OpenClaw's tool-search layer makes the model guess tool ids; small models write `gotoquill` (underscore).
`--server-name gotoquill` registers the server under that name.

## Manual GUI checklist

These clients can't be driven headless for free, so check them by hand before a release. Use
`examples/sample_contract.pdf`, plus a Hebrew/RTL PDF of your own (do not commit it).

| check | Claude Desktop | ChatGPT desktop | Cursor | VS Code Copilot | LM Studio |
|---|---|---|---|---|---|
| server connects and shows the gotoquill tools | ☐ | ☐ | ☐ | ☐ | ☐ |
| `request_signature` shows the preview (MCP App inline, or the page link) | ☐ | ☐ | ☐ | ☐ | ☐ |
| the signing link opens on a phone (delivery `link`) | ☐ | ☐ | ☐ | ☐ | ☐ |
| signing completes: signed PDF and audit JSON written, hashes match | ☐ | ☐ | ☐ | ☐ | ☐ |
| the agent sends the signed PDF/path back **unprompted** | ☐ | ☐ | ☐ | ☐ | ☐ |
| a Hebrew/RTL document renders and stamps correctly | ☐ | ☐ | ☐ | ☐ | ☐ |
| a long wait (> 5 min before signing) does not time out the tool call | ☐ | ☐ | ☐ | ☐ | ☐ |

Config snippet (stdio), for any client that takes the common `mcpServers` shape:

```json
{"mcpServers": {"gotoquill": {"command": "gotoquill", "args": ["mcp"]}}}
```

- **Claude Desktop:** `claude_desktop_config.json`.
- **Cursor:** `~/.cursor/mcp.json`.
- **VS Code:** `.vscode/mcp.json`. It uses `"servers"` instead of `"mcpServers"`.
- **LM Studio:** `mcp.json`.
- **ChatGPT desktop:** needs a remote connector, if your plan supports one.
