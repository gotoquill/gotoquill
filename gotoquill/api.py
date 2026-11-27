"""The local signing page (FastAPI). Served only on 127.0.0.1 by gotoquill.local, one server per request."""
from __future__ import annotations

from importlib import resources
from typing import Callable, Literal

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from . import __version__
from .core import SignError, get_service

LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


class SubmitBody(BaseModel):
    decision: Literal["sign", "decline"]
    signature_png_base64: str | None = None
    method: Literal["drawn", "typed"] | None = None
    typed_name: str | None = None
    signer_name: str | None = None
    consent: bool = False
    decline_reason: str | None = None
    use_saved: Literal["signature", "initials"] | None = None
    save_as: Literal["signature", "initials"] | None = None
    vault_nonce: str | None = None
    signer_timezone: str | None = None
    signer_utc_offset: int | None = None
    signer_locale: str | None = None
    date_format: Literal["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"] | None = None
    date_text: str | None = None
    signed_by_line: bool = False


class DeleteSavedBody(BaseModel):
    vault_nonce: str
    name: Literal["signature", "initials"] | None = None


def _err(e: SignError) -> JSONResponse:
    return JSONResponse({"error": str(e)}, status_code=e.code)


def sign_page_html(mode: str = "browser") -> str:
    html = resources.files("gotoquill").joinpath("static/sign.html").read_text(encoding="utf-8")
    return html.replace("__GOTOQUILL_MODE__", mode)


class AttemptGuard:
    """Simple lockout for share-link pages: too many wrong-token hits or failed submits -> 429 for good."""

    def __init__(self, token: str, max_bad: int, max_submits: int):
        self.token, self.max_bad, self.max_submits = token, max_bad, max_submits
        self.bad = self.submits = 0

    @property
    def locked(self) -> bool:
        return self.bad >= self.max_bad or self.submits >= self.max_submits


def create_app(on_submit: Callable[[str, str], None] | None = None, extra_hosts: set[str] | None = None,
               attempts: AttemptGuard | None = None) -> FastAPI:
    """on_submit(sign_token, status) is called after the human signs or declines.
    extra_hosts: exact extra Host names to accept (the share-link tunnel hostname; may be filled in later).
    attempts: optional AttemptGuard limiting guesses / submits on this page."""
    app = FastAPI(title="gotoquill", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    html = sign_page_html("browser")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # DNS-rebinding guard: only answer requests addressed to localhost.
        host = (request.headers.get("host") or "").rsplit(":", 1)[0]
        if host not in LOCAL_HOSTS and host != "testserver" and host not in (extra_hosts or ()):
            return JSONResponse({"error": "forbidden host"}, status_code=403)
        if attempts is not None and request.url.path.startswith("/s/"):
            import secrets as _s
            tok = request.url.path.split("/")[2]
            if attempts.locked:
                return JSONResponse({"error": "too many attempts; this link is locked"}, status_code=429)
            if not _s.compare_digest(tok.encode(), attempts.token.encode()):
                attempts.bad += 1
                return JSONResponse({"error": "link not found"}, status_code=404)

        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > get_service().s.max_signature_bytes * 2:
            return JSONResponse({"error": "request too large"}, status_code=413)
        resp = await call_next(request)
        if attempts is not None and request.method == "POST" and request.url.path.endswith("/submit") \
                and resp.status_code >= 400:
            attempts.submits += 1
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/healthz")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/s/{token}", response_class=HTMLResponse)
    def sign_page(token: str):
        return HTMLResponse(html, headers={"Content-Security-Policy":
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; frame-ancestors 'self'"})

    @app.get("/s/{token}/info")
    def sign_info(token: str):
        try:
            v = get_service().signer_view(token)
            v.pop("_id", None)
            return v
        except SignError as e:
            return _err(e)

    @app.get("/s/{token}/page/{page}.png")
    def sign_page_png(token: str, page: int):
        try:
            return Response(get_service().signer_page_png(token, page), media_type="image/png")
        except SignError as e:
            return _err(e)

    @app.post("/s/{token}/saved/delete")
    def delete_saved(token: str, body: DeleteSavedBody):
        try:
            return get_service().delete_saved(token, body.vault_nonce, body.name)
        except SignError as e:
            return _err(e)

    @app.post("/s/{token}/submit")
    def submit(token: str, body: SubmitBody, request: Request):
        try:
            r = get_service().submit(token, **body.model_dump(), include_pdf=True, ip=request.client.host if request.client else None,
                                     user_agent=request.headers.get("user-agent"))
        except SignError as e:
            return _err(e)
        if on_submit:
            on_submit(token, r["status"])
        return r

    return app
