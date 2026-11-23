# gotoquill relay

Zero-knowledge, single-use mailbox for **gotoquill** sealed links.

The signing page encrypts the request/reply with AES-256-GCM using a key that
lives only in the URL fragment (or the sealed HTML file). This relay stores and
returns **opaque ciphertext only**. It never sees plaintext, signatures, PDFs,
or keys.

## Operating model

**There is no shared public relay.** Each user (or company) deploys this
open-source Worker on **their own Cloudflare account**. Cloudflare Workers free
tier is enough for typical use; deploy takes **one command**.

When `DEMO=1` (default in `wrangler.toml`), `GET /` and `GET /health` return a
short testing notice:

> **demo / for testing only, no uptime guarantee, may be rate limited or shut
> down at any time; deploy your own for production.**

Set `DEMO=0` for a production Worker. Ciphertext only · as-is · no retention
beyond TTL / delete-on-read · set a real `ABUSE_CONTACT`.

## API

| Method | Path | Behavior |
|--------|------|----------|
| `PUT` / `POST` | `/v1/box/<topic>` | Store opaque blob (max **~1 MiB**). Optional `X-TTL-Seconds` (**default 1h**, **max 24h**). |
| `GET` | `/v1/box/<topic>` | Return blob or `404`. **Delete on read** (single use). |
| `HEAD` | `/v1/box/<topic>` | Exists check without consuming. |
| `GET` | `/` or `/health` | Liveness (+ demo notice JSON when `DEMO=1`). |

- Topic: url-safe random id, 20-64 chars (`[A-Za-z0-9_-]`), typically 128+ bits.
- No accounts. No body logging. **Per-IP rate limit** (~30 req/min by default; **in-memory** on the Worker - no KV writes, so free-plan 1k KV writes/day is not burned by polling). HEAD uses a tiny existence marker + ETag. CORS open for the static signing page.

## One-command self-deploy (Cloudflare Workers)

**Prerequisites:** your own Cloudflare account, Node.js/`npx`, and a scoped API
token (see [Deploy with an API token](#deploy-with-an-api-token) - preferred
over interactive `wrangler login` on a shared box).

```bash
cd relay/cloudflare
export CLOUDFLARE_API_TOKEN=...          # from the template link below
export CLOUDFLARE_ACCOUNT_ID=...         # optional if the token is single-account
./deploy.sh                              # creates KV if needed + wrangler deploy
```

Equivalent without the script:

```bash
cd relay/cloudflare && npm i && npx wrangler kv namespace create BOXES \
  && npx wrangler deploy
```

Then point gotoquill at **your** Worker:

```bash
export GOTOQUILL_RELAY_URL=https://gotoquill-relay.<your-subdomain>.workers.dev
export GOTOQUILL_RELAY_TYPE=gotoquill
```

Cloud / remote-MCP (`gotoquill mcp --http` / `tunnel`) sets `GOTOQUILL_CLOUD=1`,
which prefers gotoquill - but **requires** `GOTOQUILL_RELAY_URL`. There is no
built-in default URL.

For production, set `DEMO = "0"` in `wrangler.toml` (or `[vars]`) and use a real
abuse contact.

### Deploy to Cloudflare button

A one-click deploy link can be added after the owner chooses and publishes the public repository. Until then, use the local deployment instructions below for your own relay.

## Deploy with an API token

No interactive browser login on an agent box. Create a **scoped** token in the
Cloudflare dashboard, set env vars, run `./deploy.sh`.

### 1. Create the token (direct template link)

**User API token (recommended):**

https://dash.cloudflare.com/profile/api-tokens?permissionGroupKeys=%5B%7B%22key%22%3A%22workers_scripts%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22workers_kv_storage%22%2C%22type%22%3A%22edit%22%7D%2C%7B%22key%22%3A%22account_settings%22%2C%22type%22%3A%22read%22%7D%5D&accountId=%2A&zoneId=all&name=gotoquill-relay-deploy

Permissions to confirm:

| Permission | Access |
|------------|--------|
| **Workers Scripts** | Edit |
| **Workers KV Storage** | Edit |
| **Account Settings** | Read |

Account resources: **your** account that will own the Worker.

### 2. Env vars (do not commit the token)

```bash
export CLOUDFLARE_API_TOKEN="<token>"
export CLOUDFLARE_ACCOUNT_ID="<32-char account id>"   # if wrangler asks / multi-account
```

Account ID: Cloudflare dashboard → overview → **Account ID**.

### 3. Deploy

```bash
cd relay/cloudflare && ./deploy.sh
```

Then:

```bash
export GOTOQUILL_RELAY_URL=https://gotoquill-relay.<your-subdomain>.workers.dev
export GOTOQUILL_RELAY_TYPE=gotoquill
```

**Do not commit the token.**

## Smoke test (after your deploy)

```bash
curl -sS "$GOTOQUILL_RELAY_URL/health"
# expect JSON with "ok": true (and the demo notice if DEMO=1)

TOPIC=$(python3 -c 'import secrets; print(secrets.token_urlsafe(16))')
echo test | curl -sS -X PUT --data-binary @- "$GOTOQUILL_RELAY_URL/v1/box/$TOPIC"
curl -sS "$GOTOQUILL_RELAY_URL/v1/box/$TOPIC"
# expect "test", then a second GET returns 404
```

## Self-host / local tests (Python)

```bash
cd relay/python
pip install -r requirements.txt
# production self-host: GOTOQUILL_RELAY_DEMO=0
uvicorn gotoquill_relay.app:app --host 127.0.0.1 --port 8788
```

```bash
export GOTOQUILL_RELAY_URL=http://127.0.0.1:8788
export GOTOQUILL_RELAY_TYPE=gotoquill
```

## Plugging into gotoquill

| Env | Meaning |
|-----|---------|
| `GOTOQUILL_RELAY_URL` / `GOTOQUILL_RELAY` | **Required** for gotoquill - your Worker base URL. |
| `GOTOQUILL_RELAY_TYPE` | `ntfy` or `gotoquill`. |
| `GOTOQUILL_CLOUD=1` | Prefer gotoquill (set by `gotoquill mcp --http` / `tunnel`); still needs `GOTOQUILL_RELAY_URL`. |

The sealed-link fragment gains `rt=gotoquill` so the signing page uses
`/v1/box/...`. Crypto is unchanged (AES-256-GCM + fragment key).

## Wait / poll mode (cloud agents)

```bash
gotoquill wait <request_id>          # polls ~3-5s with backoff; prints JSON
# or MCP: wait_for_signature(request_id=..., wait_seconds=600)
```

Fallback: Muse cron/hook calling `get_signature_status` every minute until done.
