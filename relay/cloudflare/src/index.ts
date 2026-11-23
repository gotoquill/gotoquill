/**
 * gotoquill relay. Cloudflare Worker (KV-backed).
 *
 * Zero-knowledge single-use mailbox for AES-GCM ciphertext only.
 * Open-source: each assistant/company should deploy their own.
 * Each user deploys on their own Cloudflare account. DEMO=1 → testing-only NOTICE on / and /health.
 *
 * API:
 *   PUT|POST /v1/box/<topic> . store opaque blob (max ~1 MiB), TTL ≤ 24h
 *   GET       /v1/box/<topic> . return blob or 404; delete on read
 *   HEAD      /v1/box/<topic> . exists? (tiny marker key + ETag; no delete)
 *   GET / or /health         . liveness + demo notice (JSON)
 *
 * No accounts. Bodies are never logged. CORS open for the static signing page.
 * Ciphertext only; as-is; no retention beyond TTL; best-effort single-use.
 *
 * Free-tier note: rate limiting is in-memory per isolate (no KV writes). KV is
 * used only for mailbox blobs + a tiny existence marker so HEAD polls stay cheap.
 */
export interface Env {
  BOXES: KVNamespace;
  DEFAULT_TTL?: string;
  MAX_TTL?: string;
  MAX_BYTES?: string;
  RATE_MAX?: string;
  ABUSE_CONTACT?: string;
  /** "1" (default) = demo labelling on / and /health; "0" for your own production deploy */
  DEMO?: string;
  NOTICE?: string;
}

const NOTICE_DEFAULT =
  "demo / for testing only, no uptime guarantee, may be rate limited or shut down at any time; deploy your own for production";

const MAX_BYTES_DEFAULT = 1 * 1024 * 1024; // ~1 MiB (demo-strict)
const DEFAULT_TTL_DEFAULT = 3600; // 1 hour
const MAX_TTL_DEFAULT = 24 * 3600; // 24 hours
const RATE_WINDOW_SEC = 60;
const RATE_MAX_DEFAULT = 30; // requests / IP / minute
const TOPIC_RE = /^[A-Za-z0-9_-]{20,64}$/;

const CORS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, PUT, POST, HEAD, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-TTL-Seconds, If-None-Match",
  "Access-Control-Expose-Headers": "ETag",
  "Access-Control-Max-Age": "86400",
};

/** Per-isolate sliding window. Best-effort (resets on new isolate); avoids KV writes on the free plan. */
const hitsByIp = new Map<string, number[]>();

function cors(res: Response): Response {
  const h = new Headers(res.headers);
  for (const [k, v] of Object.entries(CORS)) h.set(k, v);
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
}

function num(envVal: string | undefined, fallback: number): number {
  const n = parseInt(envVal || "", 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

function noticeText(env: Env): string {
  return (env.NOTICE || NOTICE_DEFAULT).trim();
}

function isDemo(env: Env): boolean {
  const d = (env.DEMO ?? "1").toLowerCase();
  return d !== "0" && d !== "false" && d !== "no" && d !== "off";
}

function healthPayload(env: Env): object {
  const maxBytes = num(env.MAX_BYTES, MAX_BYTES_DEFAULT);
  const defaultTtl = num(env.DEFAULT_TTL, DEFAULT_TTL_DEFAULT);
  const maxTtl = num(env.MAX_TTL, MAX_TTL_DEFAULT);
  const rateMax = num(env.RATE_MAX, RATE_MAX_DEFAULT);
  return {
    ok: true,
    service: "gotoquill-relay",
    demo: isDemo(env),
    notice: isDemo(env) ? noticeText(env) : "self-hosted gotoquill relay",
    limits: {
      max_bytes: maxBytes,
      default_ttl_seconds: defaultTtl,
      max_ttl_seconds: maxTtl,
      rate_limit_per_ip_per_minute: rateMax,
      rate_limit_backend: "memory",
    },
    abuse: env.ABUSE_CONTACT || "abuse@example.com",
    deploy_your_own: "https://github.com/gotoquill/gotoquill/tree/main/relay",
  };
}

function ttlFrom(req: Request, env: Env): number {
  const defaultTtl = num(env.DEFAULT_TTL, DEFAULT_TTL_DEFAULT);
  const maxTtl = num(env.MAX_TTL, MAX_TTL_DEFAULT);
  const hdr = req.headers.get("X-TTL-Seconds");
  const q = new URL(req.url).searchParams.get("ttl");
  const raw = hdr || q || String(defaultTtl);
  const n = parseInt(raw, 10);
  if (!Number.isFinite(n)) return defaultTtl;
  return Math.max(60, Math.min(n, maxTtl));
}

function topicOf(url: URL): string | null {
  const m = url.pathname.match(/^\/v1\/box\/([A-Za-z0-9_-]{20,64})$/);
  return m ? m[1] : null;
}

function clientIp(req: Request): string {
  return req.headers.get("CF-Connecting-IP") || req.headers.get("X-Forwarded-For")?.split(",")[0]?.trim() || "unknown";
}

/** Tiny existence marker. HEAD reads this instead of the full ciphertext. */
function exKey(topic: string): string {
  return `ex:${topic}`;
}

function allow(env: Env, ip: string): boolean {
  const rateMax = num(env.RATE_MAX, RATE_MAX_DEFAULT);
  const now = Date.now() / 1000;
  let q = hitsByIp.get(ip);
  if (!q) {
    q = [];
    hitsByIp.set(ip, q);
  }
  // Drop timestamps outside the window
  while (q.length && now - q[0] > RATE_WINDOW_SEC) q.shift();
  if (q.length >= rateMax) return false;
  q.push(now);
  // Bound map growth for many unique IPs
  if (hitsByIp.size > 10_000) {
    for (const [k, v] of hitsByIp) {
      if (!v.length || now - v[v.length - 1] > RATE_WINDOW_SEC * 2) hitsByIp.delete(k);
    }
  }
  return true;
}

async function etagOf(buf: ArrayBuffer): Promise<string> {
  const dig = await crypto.subtle.digest("SHA-256", buf);
  const hex = [...new Uint8Array(dig)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `"${hex.slice(0, 32)}"`;
}

export default {
  async fetch(request: Request, env: Env, _ctx: ExecutionContext): Promise<Response> {
    if (request.method === "OPTIONS") {
      return cors(new Response(null, { status: 204 }));
    }

    const url = new URL(request.url);
    if (url.pathname === "/" || url.pathname === "/health") {
      const body = JSON.stringify(healthPayload(env), null, 2) + "\n";
      return cors(
        new Response(body, {
          headers: {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Gotoquill-Relay-Notice": isDemo(env) ? noticeText(env) : "self-hosted",
          },
        }),
      );
    }

    const topic = topicOf(url);
    if (!topic || !TOPIC_RE.test(topic)) {
      return cors(new Response("not found", { status: 404 }));
    }

    try {
      if (!allow(env, clientIp(request))) {
        return cors(new Response("rate limited", { status: 429 }));
      }

      const maxBytes = num(env.MAX_BYTES, MAX_BYTES_DEFAULT);

      if (request.method === "PUT" || request.method === "POST") {
        const buf = await request.arrayBuffer();
        if (buf.byteLength === 0) return cors(new Response("empty body", { status: 400 }));
        if (buf.byteLength > maxBytes) return cors(new Response("payload too large", { status: 413 }));
        const ttl = ttlFrom(request, env);
        const etag = await etagOf(buf);
        // Two writes: blob + tiny marker. Marker keeps HEAD polls off the full payload.
        await env.BOXES.put(topic, buf, { expirationTtl: ttl });
        await env.BOXES.put(exKey(topic), etag, { expirationTtl: ttl });
        return cors(
          new Response('{"ok":true}\n', {
            status: 201,
            headers: { "Content-Type": "application/json", ETag: etag },
          }),
        );
      }

      if (request.method === "HEAD") {
        const etag = await env.BOXES.get(exKey(topic));
        if (etag == null) {
          // Legacy blob without marker (pre-fix deploys): fall back to a full get.
          const v = await env.BOXES.get(topic);
          return cors(new Response(null, { status: v == null ? 404 : 200, headers: { "Cache-Control": "no-store" } }));
        }
        const inm = request.headers.get("If-None-Match");
        if (inm && inm === etag) {
          return cors(new Response(null, { status: 304, headers: { ETag: etag, "Cache-Control": "no-store" } }));
        }
        return cors(
          new Response(null, {
            status: 200,
            headers: { ETag: etag, "Cache-Control": "no-store" },
          }),
        );
      }

      if (request.method === "GET") {
        const v = await env.BOXES.get(topic, "arrayBuffer");
        if (v == null) {
          // Clean stray marker if any
          await env.BOXES.delete(exKey(topic));
          return cors(new Response("not found", { status: 404 }));
        }
        await env.BOXES.delete(topic);
        await env.BOXES.delete(exKey(topic));
        const etag = await etagOf(v);
        return cors(
          new Response(v, {
            status: 200,
            headers: {
              "Content-Type": "application/octet-stream",
              "Cache-Control": "no-store",
              "X-Content-Type-Options": "nosniff",
              ETag: etag,
            },
          }),
        );
      }

      return cors(new Response("method not allowed", { status: 405 }));
    } catch (_e) {
      return cors(new Response("error", { status: 500 }));
    }
  },
};
