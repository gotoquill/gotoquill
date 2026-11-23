#!/usr/bin/env bash
# One-command deploy for gotoquill relay (Cloudflare Workers + KV).
# Auth: set CLOUDFLARE_API_TOKEN (scoped) and optionally CLOUDFLARE_ACCOUNT_ID.
# Do NOT commit tokens. See relay/README.md "Deploy with an API token".
set -euo pipefail
cd "$(dirname "$0")"

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  echo "Set CLOUDFLARE_API_TOKEN first (see relay/README.md)." >&2
  exit 1
fi

if ! command -v npx >/dev/null 2>&1; then
  echo "npx (Node.js) is required." >&2
  exit 1
fi

npm install --silent

# Ensure KV namespace exists and is wired in wrangler.toml
ensure_kv() {
  local binding="$1" field="$2" flag="${3:-}"
  local id
  id=$(npx wrangler kv namespace list 2>/dev/null | python3 -c "
import json,sys
try:
  rows=json.load(sys.stdin)
except Exception:
  rows=[]
for r in rows:
  if r.get('title')=='gotoquill-relay-$binding' or r.get('title')=='$binding':
    print(r['id']); break
" || true)
  if [[ -z "$id" ]]; then
    echo "Creating KV namespace $binding..."
    # wrangler prints: { Binding: ..., id: "..." }
    out=$(npx wrangler kv namespace create "$binding" $flag)
    id=$(echo "$out" | python3 -c "import sys,re; m=re.search(r'id\s*=\s*\"([a-f0-9]+)\"', sys.stdin.read()); print(m.group(1) if m else '')")
    if [[ -z "$id" ]]; then
      id=$(echo "$out" | python3 -c "import sys,re; m=re.search(r'\"id\":\s*\"([a-f0-9]+)\"', sys.stdin.read()); print(m.group(1) if m else '')")
    fi
  fi
  if [[ -z "$id" ]]; then
    echo "Could not resolve KV id for $binding. Create it manually and edit wrangler.toml." >&2
    exit 1
  fi
  python3 - "$field" "$id" <<'PY'
import re, sys
from pathlib import Path
field, kid = sys.argv[1], sys.argv[2]
p = Path("wrangler.toml")
text = p.read_text()
text2, n = re.subn(rf"(^{field}\s*=\s*)\".*?\"", rf'\1"{kid}"', text, count=1, flags=re.M)
if n == 0:
    raise SystemExit(f"wrangler.toml missing {field}")
p.write_text(text2)
print(f"  {field} = {kid}")
PY
}

echo "Ensuring KV namespaces..."
ensure_kv BOXES id
ensure_kv BOXES preview_id --preview

echo "Deploying..."
npx wrangler deploy
echo
echo "Done. Point gotoquill at the workers.dev URL printed above:"
echo "  export GOTOQUILL_RELAY_URL=https://<worker>.<subdomain>.workers.dev"
echo "  export GOTOQUILL_RELAY_TYPE=gotoquill"
