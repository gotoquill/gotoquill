"""Minimal single-user OAuth 2.1 (DCR + PKCE) for remote MCP hosts.

ChatGPT custom MCP, Claude custom connectors, and Meta Muse all speak OAuth 2.1
with dynamic client registration (or no auth). A static bearer-only connector is
rejected by ChatGPT and awkward for Muse, so this module is the auth surface for
`gotoquill mcp --http`.

One human, one pairing code (printed once, stored 0600). The OAuth machinery
exists so those hosts can complete their connector handshake; the pairing code
is the real secret. Access/refresh tokens are stored as SHA-256 digests only.
Public URLs (issuer, metadata, WWW-Authenticate) are derived per-request from
X-Forwarded-* so a cloudflared quick tunnel works without a fixed hostname.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import html
import json
import os
import secrets
import tempfile
import threading
import time
import urllib.parse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

ACCESS_TOKEN_TTL_SECONDS = 2_592_000  # 30 days
AUTH_CODE_TTL_SECONDS = 120.0
MAX_PAIRING_FAILURES = 5
PAIRING_LOCKOUT_SECONDS = 60.0

_AUTHORIZE_FIELDS = (
    "client_id", "redirect_uri", "response_type", "state",
    "code_challenge", "code_challenge_method", "scope", "resource",
)


def _first(value: str | None) -> str:
    return (value or "").split(",")[0].strip()


def public_base_url(request: Request) -> str:
    """Public origin (scheme://host) as the tunnel client sees it."""
    scheme = _first(request.headers.get("x-forwarded-proto")) or request.url.scheme
    host = (_first(request.headers.get("x-forwarded-host"))
            or _first(request.headers.get("host"))
            or request.url.netloc)
    return f"{scheme}://{host}"


def store_dir() -> Path:
    from .envcompat import env_get, resolve_config_dir, default_data_dir
    explicit = env_get("CONFIG_DIR") or env_get("DATA_DIR")
    base = Path(explicit).expanduser() if explicit else resolve_config_dir()
    # Prefer data_dir semantics when only ~/.gotoquill (or legacy) exists as data home
    if not explicit:
        base = default_data_dir()
    d = base / "remote-mcp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pairing_path() -> Path:
    return store_dir() / "pairing.json"


def oauth_state_path() -> Path:
    return store_dir() / "oauth.json"


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".gotoquill-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def load_or_create_pairing_code(*, rotate: bool = False) -> tuple[str, bool]:
    """Return (code, created_now). Persisted 0600; printed by the CLI when created."""
    path = pairing_path()
    if not rotate:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            existing = data.get("pairing_code") if isinstance(data, dict) else None
            if isinstance(existing, str) and existing:
                return existing, False
        except (OSError, ValueError):
            pass
    code = secrets.token_urlsafe(18)
    _atomic_write_json(path, {"pairing_code": code})
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return code, True


def _sha256_hex(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _pkce_s256(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _is_allowed_redirect_uri(uri: str) -> bool:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme == "https":
        return True
    if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return True
    return False


def _append_query(url: str, params: dict[str, str]) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.extend(params.items())
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


async def _urlencoded_form(request: Request) -> Mapping[str, str]:
    raw = await request.body()
    form: dict[str, str] = {}
    for key, value in urllib.parse.parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=True):
        form.setdefault(key, value)
    return form


def _form_str(form: Mapping[str, str], key: str) -> str:
    return form.get(key, "")


class OAuthStore:
    """Thread-safe OAuth state; clients + token hashes persisted 0600."""

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path or oauth_state_path()
        self._lock = threading.RLock()
        self._clients: dict[str, dict[str, Any]] = {}
        self._access_tokens: dict[str, dict[str, Any]] = {}
        self._refresh_tokens: dict[str, dict[str, Any]] = {}
        self._auth_codes: dict[str, dict[str, Any]] = {}
        self._pairing_failures = 0
        self._pairing_lockout_until = 0.0
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for key, attr in (("clients", "_clients"), ("access_tokens", "_access_tokens"),
                          ("refresh_tokens", "_refresh_tokens")):
            val = data.get(key)
            if isinstance(val, dict):
                setattr(self, attr, val)

    def _save(self) -> None:
        _atomic_write_json(self.state_path, {
            "clients": self._clients,
            "access_tokens": self._access_tokens,
            "refresh_tokens": self._refresh_tokens,
        })

    def register_client(self, *, redirect_uris: list[str], client_name: str | None,
                        grant_types: list[str], response_types: list[str]) -> dict[str, Any]:
        client_id = secrets.token_urlsafe(24)
        record: dict[str, Any] = {
            "client_id": client_id,
            "client_id_issued_at": int(time.time()),
            "redirect_uris": redirect_uris,
            "token_endpoint_auth_method": "none",
            "grant_types": grant_types,
            "response_types": response_types,
        }
        if client_name is not None:
            record["client_name"] = client_name
        with self._lock:
            self._clients[client_id] = record
            self._save()
        return record

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._clients.get(client_id)

    def create_auth_code(self, *, client_id: str, redirect_uri: str,
                         code_challenge: str, resource: str) -> str:
        code = secrets.token_urlsafe(32)
        with self._lock:
            self._auth_codes[code] = {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "resource": resource,
                "expires": time.monotonic() + AUTH_CODE_TTL_SECONDS,
            }
        return code

    def consume_auth_code(self, code: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._auth_codes.pop(code, None)
            if record is None or time.monotonic() > record["expires"]:
                return None
            return record

    def issue_tokens(self, client_id: str) -> tuple[str, str]:
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        with self._lock:
            self._access_tokens[_sha256_hex(access_token)] = {
                "client_id": client_id,
                "expires_at": time.time() + ACCESS_TOKEN_TTL_SECONDS,
            }
            self._refresh_tokens[_sha256_hex(refresh_token)] = {"client_id": client_id}
            self._save()
        return access_token, refresh_token

    def verify_access_token(self, token: str) -> bool:
        digest = _sha256_hex(token)
        with self._lock:
            record = self._access_tokens.get(digest)
            if record is None:
                return False
            if time.time() > record["expires_at"]:
                del self._access_tokens[digest]
                self._save()
                return False
            return True

    def rotate_refresh_token(self, refresh_token: str) -> tuple[str, str] | None:
        digest = _sha256_hex(refresh_token)
        with self._lock:
            record = self._refresh_tokens.pop(digest, None)
            if record is None:
                return None
            return self.issue_tokens(str(record["client_id"]))

    def pairing_lockout_remaining(self) -> float:
        with self._lock:
            remaining = self._pairing_lockout_until - time.monotonic()
            return remaining if remaining > 0 else 0.0

    def record_pairing_failure(self) -> None:
        with self._lock:
            self._pairing_failures += 1
            if self._pairing_failures >= MAX_PAIRING_FAILURES:
                self._pairing_lockout_until = time.monotonic() + PAIRING_LOCKOUT_SECONDS

    def reset_pairing_failures(self) -> None:
        with self._lock:
            self._pairing_failures = 0
            self._pairing_lockout_until = 0.0


_PAGE_STYLE = (
    "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
    "background:#0f1115;color:#e6e6e6;display:flex;min-height:100vh;margin:0;"
    "align-items:center;justify-content:center}"
    ".card{background:#1b1e26;border:1px solid #2a2e38;border-radius:12px;padding:32px;"
    "max-width:380px;width:100%;box-shadow:0 8px 30px rgba(0,0,0,.4)}"
    "h1{font-size:18px;margin:0 0 8px}p{font-size:14px;line-height:1.5;color:#a0a6b0}"
    "input[type=text]{width:100%;box-sizing:border-box;padding:10px 12px;margin:14px 0;"
    "font-size:15px;border-radius:8px;border:1px solid #3a3f4b;background:#11141a;color:#fff}"
    "button{width:100%;padding:11px;font-size:15px;font-weight:600;border:0;border-radius:8px;"
    "background:#f2c94c;color:#1b1e26;cursor:pointer}"
    ".error{color:#ff6b6b;font-size:13px;margin-top:4px}"
)


def _error_page(message: str) -> str:
    return (f"<!doctype html><html><head><meta charset=utf-8><title>gotoquill</title>"
            f"<style>{_PAGE_STYLE}</style></head><body><div class=card>"
            f"<h1>Cannot continue</h1><p>{html.escape(message)}</p></div></body></html>")


def _render_form(params: dict[str, str], error: str | None) -> str:
    hidden = "".join(
        f'<input type=hidden name="{html.escape(k)}" value="{html.escape(params.get(k, ""))}">'
        for k in _AUTHORIZE_FIELDS
    )
    error_html = f'<p class=error>{html.escape(error)}</p>' if error else ""
    return (
        f"<!doctype html><html><head><meta charset=utf-8><title>Connect gotoquill</title>"
        f"<style>{_PAGE_STYLE}</style></head><body><div class=card>"
        f"<h1>Connect gotoquill</h1>"
        f"<p>Enter the pairing code shown when you started "
        f"<code>gotoquill mcp --http</code> (or <code>gotoquill tunnel</code>).</p>"
        f"<form method=post action=/authorize>{hidden}"
        f'<input type=text name=pairing_code autocomplete=one-time-code '
        f'placeholder="Pairing code" autofocus required>'
        f"{error_html}"
        f"<button type=submit>Authorize</button></form></div></body></html>"
    )


def _token_error(error: str, description: str, *, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _token_success(access_token: str, refresh_token: str) -> JSONResponse:
    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_TTL_SECONDS,
            "refresh_token": refresh_token,
            "scope": "",
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _exchange_auth_code(store: OAuthStore, form: Mapping[str, str]) -> Response:
    code = _form_str(form, "code")
    client_id = _form_str(form, "client_id")
    redirect_uri = _form_str(form, "redirect_uri")
    code_verifier = _form_str(form, "code_verifier")
    if not code or not code_verifier:
        return _token_error("invalid_request", "code and code_verifier are required")
    record = store.consume_auth_code(code)
    if record is None:
        return _token_error("invalid_grant", "authorization code is invalid or expired")
    if record["client_id"] != client_id:
        return _token_error("invalid_grant", "client_id does not match the authorization code")
    if record["redirect_uri"] != redirect_uri:
        return _token_error("invalid_grant", "redirect_uri does not match the authorization code")
    if not hmac.compare_digest(_pkce_s256(code_verifier), str(record["code_challenge"])):
        return _token_error("invalid_grant", "PKCE verification failed")
    access_token, refresh_token = store.issue_tokens(client_id)
    return _token_success(access_token, refresh_token)


def _exchange_refresh(store: OAuthStore, form: Mapping[str, str]) -> Response:
    refresh_token = _form_str(form, "refresh_token")
    if not refresh_token:
        return _token_error("invalid_request", "refresh_token is required")
    rotated = store.rotate_refresh_token(refresh_token)
    if rotated is None:
        return _token_error("invalid_grant", "refresh_token is invalid or already used")
    access_token, new_refresh = rotated
    return _token_success(access_token, new_refresh)


def mount_oauth_routes(app: FastAPI, store: OAuthStore, pairing_code: str, *, mcp_path: str = "/mcp") -> None:
    """Register public OAuth discovery + DCR + authorize + token on app."""

    def _protected_resource_doc(request: Request) -> dict[str, Any]:
        base = public_base_url(request)
        return {
            "resource": f"{base}{mcp_path}",
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
            "scopes_supported": [],
        }

    def _authorization_server_doc(request: Request) -> dict[str, Any]:
        base = public_base_url(request)
        return {
            "issuer": base,
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "registration_endpoint": f"{base}/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": [],
        }

    @app.get("/.well-known/oauth-protected-resource")
    @app.get(f"/.well-known/oauth-protected-resource{mcp_path}")
    async def protected_resource(request: Request) -> JSONResponse:
        return JSONResponse(_protected_resource_doc(request))

    async def authorization_server_metadata(request: Request) -> JSONResponse:
        return JSONResponse(_authorization_server_doc(request))

    for route in (
        "/.well-known/oauth-authorization-server",
        f"/.well-known/oauth-authorization-server{mcp_path}",
        "/.well-known/openid-configuration",
        f"/.well-known/openid-configuration{mcp_path}",
    ):
        app.get(route)(authorization_server_metadata)

    @app.post("/register")
    async def register_dcr(request: Request) -> Response:
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "invalid_client_metadata",
                                 "error_description": "request body is not valid JSON"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_client_metadata",
                                 "error_description": "request body must be a JSON object"}, status_code=400)
        redirect_uris = body.get("redirect_uris")
        if (not isinstance(redirect_uris, list) or not redirect_uris
                or not all(isinstance(uri, str) for uri in redirect_uris)):
            return JSONResponse({"error": "invalid_redirect_uri",
                                 "error_description": "redirect_uris is required"}, status_code=400)
        for uri in redirect_uris:
            if not _is_allowed_redirect_uri(uri):
                return JSONResponse({"error": "invalid_redirect_uri",
                                     "error_description": f"redirect_uri must be https (or http loopback): {uri}"},
                                    status_code=400)
        client_name = body.get("client_name")
        grant_types = body.get("grant_types") or ["authorization_code", "refresh_token"]
        response_types = body.get("response_types") or ["code"]
        record = store.register_client(
            redirect_uris=list(redirect_uris),
            client_name=client_name if isinstance(client_name, str) else None,
            grant_types=list(grant_types) if isinstance(grant_types, list) else ["authorization_code", "refresh_token"],
            response_types=list(response_types) if isinstance(response_types, list) else ["code"],
        )
        return JSONResponse(record, status_code=201)

    @app.get("/authorize")
    async def authorize_get(request: Request) -> Response:
        q = request.query_params
        client_id = q.get("client_id", "")
        redirect_uri = q.get("redirect_uri", "")
        client = store.get_client(client_id)
        if client is None:
            return HTMLResponse(_error_page("Unknown client_id."), status_code=400)
        if redirect_uri not in client["redirect_uris"]:
            return HTMLResponse(_error_page("redirect_uri does not match a registered value."), status_code=400)
        if q.get("response_type", "") != "code":
            return HTMLResponse(_error_page("response_type must be 'code'."), status_code=400)
        if q.get("code_challenge_method", "") != "S256" or not q.get("code_challenge", ""):
            return HTMLResponse(_error_page("PKCE with code_challenge_method=S256 is required."), status_code=400)
        params = {key: q.get(key, "") for key in _AUTHORIZE_FIELDS}
        return HTMLResponse(_render_form(params, error=None))

    @app.post("/authorize")
    async def authorize_post(request: Request) -> Response:
        form = await _urlencoded_form(request)
        client_id = _form_str(form, "client_id")
        redirect_uri = _form_str(form, "redirect_uri")
        client = store.get_client(client_id)
        if client is None:
            return HTMLResponse(_error_page("Unknown client_id."), status_code=400)
        if redirect_uri not in client["redirect_uris"]:
            return HTMLResponse(_error_page("redirect_uri does not match a registered value."), status_code=400)
        params = {key: _form_str(form, key) for key in _AUTHORIZE_FIELDS}
        lockout = store.pairing_lockout_remaining()
        if lockout > 0:
            return HTMLResponse(
                _render_form(params, error=f"Too many attempts. Try again in {int(lockout) + 1}s."),
                status_code=429,
            )
        submitted = _form_str(form, "pairing_code")
        if not (submitted and hmac.compare_digest(submitted, pairing_code)):
            store.record_pairing_failure()
            return HTMLResponse(_render_form(params, error="Incorrect pairing code."), status_code=200)
        store.reset_pairing_failures()
        code = store.create_auth_code(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=params["code_challenge"],
            resource=params["resource"],
        )
        location = _append_query(redirect_uri, {"code": code, "state": params["state"]})
        return RedirectResponse(location, status_code=302)

    @app.post("/token")
    async def token(request: Request) -> Response:
        form = await _urlencoded_form(request)
        grant_type = _form_str(form, "grant_type")
        if grant_type == "authorization_code":
            return _exchange_auth_code(store, form)
        if grant_type == "refresh_token":
            return _exchange_refresh(store, form)
        return _token_error("unsupported_grant_type", f"unsupported grant_type: {grant_type!r}")


def require_bearer(request: Request, store: OAuthStore, pairing_code: str, *, mcp_path: str = "/mcp") -> None:
    """Raise 401 with WWW-Authenticate resource_metadata unless bearer is valid.

    Accepts either a minted OAuth access token or the pairing code itself (handy
    for curl / hosts that support a static Authorization header).
    """
    header = request.headers.get("authorization", "")
    scheme, _, raw = header.partition(" ")
    token_value = raw.strip()
    if scheme.lower() == "bearer" and token_value:
        if hmac.compare_digest(token_value, pairing_code) or store.verify_access_token(token_value):
            return
    base = public_base_url(request)
    raise HTTPException(
        status_code=401,
        detail="missing or invalid access token",
        headers={
            "WWW-Authenticate": (
                f'Bearer realm="gotoquill", '
                f'resource_metadata="{base}/.well-known/oauth-protected-resource"'
            )
        },
    )
