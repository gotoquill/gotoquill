"""Minimal Starlette twin of the Cloudflare Worker: PUT/GET/HEAD /v1/box/<topic>.

Ciphertext only. No accounts. Bodies are never logged. Delete-on-read + short TTL.
Open-source: each user deploys their own (no shared public relay).
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict, deque

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

NOTICE_DEFAULT = (
    "demo / for testing only, no uptime guarantee, may be rate limited or shut down at any time; "
    "deploy your own for production"
)

MAX_BYTES = int(os.environ.get("GOTOQUILL_RELAY_MAX_BYTES", str(1 * 1024 * 1024)))  # ~1 MiB
DEFAULT_TTL = int(os.environ.get("GOTOQUILL_RELAY_DEFAULT_TTL", "3600"))  # 1 hour
MAX_TTL = int(os.environ.get("GOTOQUILL_RELAY_MAX_TTL", str(24 * 3600)))  # 24 hours
TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
RATE_WINDOW = 60.0
RATE_MAX = int(os.environ.get("GOTOQUILL_RELAY_RATE_MAX", "30"))  # req / IP / minute
ABUSE_CONTACT = os.environ.get("GOTOQUILL_RELAY_ABUSE", "abuse@example.com")
DEMO = os.environ.get("GOTOQUILL_RELAY_DEMO", "1").lower() not in ("0", "false", "no", "off")
NOTICE = os.environ.get("GOTOQUILL_RELAY_NOTICE", NOTICE_DEFAULT).strip()


class _Store:
    """In-memory mailbox: topic -> (blob, expires_at). Delete on successful GET."""

    def __init__(self) -> None:
        self._boxes: dict[str, tuple[bytes, float]] = {}
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def put(self, topic: str, data: bytes, ttl: int) -> None:
        self._boxes[topic] = (data, time.monotonic() + ttl)

    def get(self, topic: str, *, consume: bool) -> bytes | None:
        self._purge()
        item = self._boxes.get(topic)
        if item is None:
            return None
        data, exp = item
        if time.monotonic() >= exp:
            self._boxes.pop(topic, None)
            return None
        if consume:
            self._boxes.pop(topic, None)
        return data

    def exists(self, topic: str) -> bool:
        return self.get(topic, consume=False) is not None

    def _purge(self) -> None:
        now = time.monotonic()
        dead = [k for k, (_, exp) in self._boxes.items() if now >= exp]
        for k in dead:
            self._boxes.pop(k, None)

    def allow(self, ip: str) -> bool:
        q = self._hits[ip]
        now = time.monotonic()
        while q and now - q[0] > RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_MAX:
            return False
        q.append(now)
        return True


STORE = _Store()


def _client_ip(request: Request) -> str:
    xff = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return (request.client.host if request.client else "unknown") or "unknown"


def _ttl_from(request: Request) -> int:
    raw = request.headers.get("x-ttl-seconds") or request.query_params.get("ttl") or str(DEFAULT_TTL)
    try:
        ttl = int(raw)
    except ValueError:
        ttl = DEFAULT_TTL
    return max(60, min(ttl, MAX_TTL))


def _health_payload() -> dict:
    return {
        "ok": True,
        "service": "gotoquill-relay",
        "demo": DEMO,
        "notice": NOTICE if DEMO else "self-hosted gotoquill relay",
        "limits": {
            "max_bytes": MAX_BYTES,
            "default_ttl_seconds": DEFAULT_TTL,
            "max_ttl_seconds": MAX_TTL,
            "rate_limit_per_ip_per_minute": RATE_MAX,
        },
        "abuse": ABUSE_CONTACT,
        "deploy_your_own": "https://github.com/gotoquill/gotoquill/tree/main/relay",
    }


async def health(_: Request) -> Response:
    body = json.dumps(_health_payload(), indent=2) + "\n"
    headers = {
        "Cache-Control": "no-store",
        "X-Gotoquill-Relay-Notice": NOTICE if DEMO else "self-hosted",
    }
    return Response(body, media_type="application/json", headers=headers)


async def put_box(request: Request) -> Response:
    topic = request.path_params["topic"]
    if not TOPIC_RE.match(topic):
        return Response("bad topic", status_code=400)
    if not STORE.allow(_client_ip(request)):
        return Response("rate limited", status_code=429)
    body = await request.body()
    if not body:
        return Response("empty body", status_code=400)
    if len(body) > MAX_BYTES:
        return Response("payload too large", status_code=413)
    STORE.put(topic, bytes(body), _ttl_from(request))
    return Response('{"ok":true}\n', status_code=201, media_type="application/json")


async def get_box(request: Request) -> Response:
    """GET consumes; HEAD (auto-handled by Starlette on the GET route) must not."""
    topic = request.path_params["topic"]
    if not TOPIC_RE.match(topic):
        return Response("bad topic" if request.method != "HEAD" else None, status_code=400)
    if not STORE.allow(_client_ip(request)):
        return Response("rate limited" if request.method != "HEAD" else None, status_code=429)
    consume = request.method != "HEAD"
    data = STORE.get(topic, consume=consume)
    if data is None:
        return Response("not found" if request.method != "HEAD" else None, status_code=404)
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if request.method == "HEAD":
        return Response(status_code=200, headers=headers)
    return Response(data, media_type="application/octet-stream", headers=headers)


def create_app(store: _Store | None = None) -> Starlette:
    global STORE
    if store is not None:
        STORE = store
    routes = [
        Route("/", health),
        Route("/health", health),
        Route("/v1/box/{topic}", put_box, methods=["PUT", "POST"]),
        Route("/v1/box/{topic}", get_box, methods=["GET", "HEAD"]),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "PUT", "POST", "HEAD", "OPTIONS"],
        allow_headers=["Content-Type", "X-TTL-Seconds"],
        expose_headers=["X-Content-Type-Options", "X-Gotoquill-Relay-Notice"],
        max_age=86400,
    )
    return app


app = create_app()


def main() -> None:
    import uvicorn
    uvicorn.run("gotoquill_relay.app:app", host="127.0.0.1", port=8788, reload=False)


if __name__ == "__main__":
    main()
