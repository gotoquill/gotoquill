"""Streamable-HTTP MCP transport + OAuth + download routes for cloud assistants."""
from __future__ import annotations

from .envcompat import env_int

import contextlib
import os
import sys
from collections.abc import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from . import cloud_io
from .save_page import DOWNLOAD_HEADERS, attachment_disposition, safe_filename, save_page
from .mcp_oauth import (
    OAuthStore,
    load_or_create_pairing_code,
    mount_oauth_routes,
    require_bearer,
)
from .mcp_server import build_server

DEFAULT_PORT = 8787
MCP_PATH = "/mcp"


class _BearerGate(BaseHTTPMiddleware):
    """Require a valid bearer on /mcp; leave OAuth discovery and /download public."""

    def __init__(self, app: ASGIApp, store: OAuthStore, pairing_code: str, mcp_path: str = MCP_PATH):
        super().__init__(app)
        self.store = store
        self.pairing_code = pairing_code
        self.mcp_path = mcp_path.rstrip("/") or "/mcp"

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # /download/{token} is gated by the unguessable token alone so a human can open
        # the link from chat without an Authorization header. /mcp always needs Bearer.
        protected = path == self.mcp_path or path.startswith(self.mcp_path + "/")
        if protected:
            try:
                require_bearer(request, self.store, self.pairing_code, mcp_path=self.mcp_path)
            except Exception as e:  # HTTPException from FastAPI
                from fastapi import HTTPException
                if isinstance(e, HTTPException):
                    return JSONResponse({"error": e.detail}, status_code=e.status_code, headers=e.headers or {})
                raise
        return await call_next(request)


def create_http_app(*, pairing_code: str | None = None, public_base: str | None = None,
                    mcp_path: str = MCP_PATH, host_hint: str = "127.0.0.1") -> tuple[FastAPI, str, bool]:
    """Build the FastAPI app. Returns (app, pairing_code, pairing_was_created)."""
    code, created = (pairing_code, False) if pairing_code else load_or_create_pairing_code()
    store = OAuthStore()

    from mcp.server.transport_security import TransportSecuritySettings

    mcp = build_server()
    # Disable DNS rebinding protection so trycloudflare.com Host headers work.
    transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    mcp_asgi = mcp.streamable_http_app(
        streamable_http_path=mcp_path,
        host=host_hint,
        transport_security=transport_security,
        max_request_body_size=env_int("MAX_PDF_MB", 50) * 1024 * 1024 + 1024 * 1024,
        json_response=True,  # simpler for many remote clients
        stateless_http=True,
    )
    session_manager = mcp._lowlevel_server._session_manager  # noqa: SLF001. SDK wires this here

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Mounted Starlette sub-apps do not always get their lifespan entered under FastAPI;
        # run the MCP session manager on the parent so /mcp works.
        async with session_manager.run():
            yield

    app = FastAPI(title="gotoquill remote MCP", version="0.2.0", lifespan=lifespan)
    mount_oauth_routes(app, store, code, mcp_path=mcp_path)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "gotoquill"}

    @app.api_route("/download/{token}", methods=["GET", "HEAD"])
    async def download(token: str, request: Request) -> Response:
        rec = cloud_io.pop_download(token)
        if rec is None:
            return JSONResponse({"error": "download not found or expired"}, status_code=404, headers=DOWNLOAD_HEADERS)
        path = rec["path"]
        if not os.path.isfile(path):
            return JSONResponse({"error": "file gone"}, status_code=404, headers=DOWNLOAD_HEADERS)
        filename = safe_filename(rec["name"])
        if request.query_params.get("save") == "1":
            return save_page(f"/download/{token}", filename, head=request.method == "HEAD")
        return FileResponse(path, filename=filename, media_type="application/pdf", headers={
            **DOWNLOAD_HEADERS, "content-disposition": attachment_disposition(filename),
        })

    # Mount the MCP Starlette app. Its routes include /mcp (absolute path inside).
    # Mounting at "" keeps those absolute paths working. Child lifespan is unused;
    # parent lifespan above runs session_manager.
    app.mount("", mcp_asgi)

    app.add_middleware(_BearerGate, store=store, pairing_code=code, mcp_path=mcp_path)

    if public_base:
        cloud_io.set_http_public_base(public_base)
    else:
        cloud_io.set_http_public_base(f"http://127.0.0.1:{DEFAULT_PORT}")

    app.state.oauth_store = store  # type: ignore[attr-defined]
    app.state.pairing_code = code  # type: ignore[attr-defined]
    app.state.mcp_server = mcp  # type: ignore[attr-defined]
    app.state.session_manager = session_manager  # type: ignore[attr-defined]
    return app, code, created


def run_http(*, host: str = "127.0.0.1", port: int = DEFAULT_PORT, public_url: str | None = None,
             pairing_code: str | None = None) -> None:
    """Serve Streamable HTTP MCP on host:port (blocking)."""
    # Cloud assistants often block ntfy.sh. prefer gotoquill relay (requires GOTOQUILL_RELAY_URL).
    os.environ.setdefault("GOTOQUILL_CLOUD", "1")
    base = (public_url or f"http://{host}:{port}").rstrip("/")
    app, code, created = create_http_app(pairing_code=pairing_code, public_base=base, host_hint=host)
    cloud_io.set_http_public_base(base)
    print(f"gotoquill remote MCP listening on http://{host}:{port}{MCP_PATH}", file=sys.stderr)
    print(f"  public base: {base}", file=sys.stderr)
    if created:
        print("  pairing code (save this; shown only once):", file=sys.stderr)
        print(f"    {code}", file=sys.stderr)
        print(f"  stored at {os.path.expanduser('~/.gotoquill')}/remote-mcp/pairing.json (mode 0600)",
              file=sys.stderr)
    else:
        print("  pairing code already on disk (not re-printed). Delete remote-mcp/pairing.json to rotate.",
              file=sys.stderr)
    print("  Auth: OAuth 2.1 + DCR (ChatGPT / Claude / Muse). Bearer may also be the pairing code.",
          file=sys.stderr)
    uvicorn.run(app, host=host, port=port, log_level="info")


def run_tunnel(*, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
    """Start MCP HTTP + a Cloudflare quick tunnel; print the public HTTPS URL."""
    import threading
    import time

    from .tunnel import CloudflareTunnel

    os.environ.setdefault("GOTOQUILL_CLOUD", "1")
    app, code, created = create_http_app(host_hint=host)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    t = threading.Thread(target=server.run, name="gotoquill-http", daemon=True)
    t.start()

    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)

    tunnel = CloudflareTunnel(port)
    try:
        url = tunnel.start()
    except Exception as e:
        server.should_exit = True
        raise SystemExit(f"tunnel failed: {e}") from e
    cloud_io.set_http_public_base(url)
    mcp_url = f"{url}{MCP_PATH}"
    print("gotoquill tunnel ready", file=sys.stderr)
    print(f"  MCP URL:  {mcp_url}", file=sys.stderr)
    print(f"  local:    http://{host}:{port}{MCP_PATH}", file=sys.stderr)
    if created:
        print("  pairing code (save this; shown only once):", file=sys.stderr)
        print(f"    {code}", file=sys.stderr)
    else:
        print("  pairing code already on disk (not re-printed).", file=sys.stderr)
    print("  Paste the MCP URL into ChatGPT / Claude / Muse as a custom connector (OAuth).",
          file=sys.stderr)
    print("  Ctrl+C stops the tunnel and the local server.", file=sys.stderr)
    try:
        while t.is_alive() and tunnel.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        tunnel.stop()
        server.should_exit = True
