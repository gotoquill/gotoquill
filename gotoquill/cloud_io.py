"""Cloud-agent PDF in/out helpers for remote MCP (HTTP) mode.

Cloud assistants cannot read local file paths on the user's machine. When running
over Streamable HTTP:

* Input: accept ``pdf_base64`` or ``pdf_url`` (fetched by this process on the
  user's device) and materialize a local temp PDF under the data dir.
* Output: after signing, expose a short-lived tokenized download URL served by
  the same local HTTP process (through the tunnel). Optionally include base64
  for small files. The PDF bytes stay on the user's device; only the chat that
  called the tool receives a download link (or base64) through the MCP session.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import threading
import time
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit, urljoin
from pathlib import Path
from typing import Any

from .config import get_settings
from .core import SignError

# Soft cap for returning base64 in the tool result (keeps chat payloads small).
BASE64_RETURN_MAX = 1_500_000  # ~1.1 MiB decoded
DOWNLOAD_TTL_SECONDS = 3 * 3600
_MAX_FETCH_BYTES = 50 * 1024 * 1024

_lock = threading.RLock()
_downloads: dict[str, dict[str, Any]] = {}  # token -> {path, expires, name, sha256}
_http_public_base: str | None = None  # set by mcp_http when serving


def set_http_public_base(url: str | None) -> None:
    """Base URL used to mint absolute download links (tunnel or localhost)."""
    global _http_public_base
    _http_public_base = (url or "").rstrip("/") or None


def get_http_public_base() -> str | None:
    return _http_public_base


def http_mode_active() -> bool:
    return _http_public_base is not None


def _decode_pdf_base64(raw: str) -> bytes:
    s = (raw or "").strip()
    if "," in s and s.lower().startswith("data:"):
        s = s.split(",", 1)[1]
    try:
        data = base64.b64decode(s, validate=False)
    except Exception as e:  # noqa: BLE001
        raise SignError(f"pdf_base64 is not valid base64: {e}", 400) from e
    if not data.startswith(b"%PDF"):
        raise SignError("pdf_base64 does not look like a PDF (missing %PDF header)", 400)
    max_b = get_settings().max_pdf_bytes
    if len(data) > max_b:
        raise SignError(f"PDF too large ({len(data)} bytes; max {max_b})", 400)
    return data


def _public_destination(url: str) -> tuple[str, str, list[str]]:
    """Validate every DNS answer; callers connect to a validated IP, never re-resolve."""
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or parsed.port not in (None, 443)):
            raise ValueError("HTTPS URL on port 443 required")
        host = parsed.hostname.encode("idna").decode("ascii")
        if any(c.isspace() for c in host) or "%" in host:
            raise ValueError("invalid host")
        addresses = list(dict.fromkeys(a[4][0] for a in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
        if not addresses:
            raise ValueError("no addresses")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            ip = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped else ip
            if isinstance(ip, ipaddress.IPv6Address) and (
                    ip in ipaddress.ip_network("64:ff9b::/96") or ip in ipaddress.ip_network("64:ff9b:1::/48")
                    or ip.sixtofour is not None or ip.teredo is not None):
                raise ValueError("translated destination")
            if not ip.is_global or ip.is_multicast or ip.is_unspecified:
                raise ValueError("private destination")
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        return host, target, addresses
    except (ValueError, OSError, UnicodeError) as e:
        raise SignError("pdf_url must resolve only to public HTTPS destinations", 400) from e


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str):
        super().__init__(host, timeout=30, context=ssl.create_default_context())
        self._address = address

    def connect(self) -> None:
        # Preserve TLS hostname verification/SNI while preventing DNS rebinding.
        sock = socket.create_connection((self._address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def _fetch_pdf_url(url: str) -> bytes:
    current = (url or "").strip()
    max_b = min(get_settings().max_pdf_bytes, _MAX_FETCH_BYTES)
    for hop in range(4):
        host, target, addresses = _public_destination(current)
        conn = _PinnedHTTPSConnection(host, addresses[0])
        try:
            conn.request("GET", target, headers={"User-Agent": "gotoquill", "Accept": "application/pdf", "Accept-Encoding": "identity"})
            with conn.getresponse() as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.getheader("Location")
                    if not location or hop == 3:
                        raise SignError("pdf_url redirect limit exceeded", 400)
                    current = urljoin(current, location)
                    continue  # Next hop validates scheme, hostname and every DNS answer.
                if resp.status != 200:
                    raise SignError(f"pdf_url fetch failed: HTTP {resp.status}", 400)
                if resp.getheader("Content-Encoding", "identity").lower() != "identity":
                    raise SignError("compressed HTTP responses are not supported", 400)
                length = resp.getheader("Content-Length")
                if length and (not length.isdecimal() or int(length) > max_b):
                    raise SignError("pdf_url body exceeds max size", 413)
                chunks: list[bytes] = []
                total = 0
                while block := resp.read(min(64 * 1024, max_b + 1 - total)):
                    total += len(block)
                    if total > max_b:
                        raise SignError("pdf_url body exceeds max size", 413)
                    chunks.append(block)
                data = b"".join(chunks)
        except SignError:
            raise
        except Exception as e:
            raise SignError("pdf_url HTTPS fetch failed", 400) from e
        finally:
            conn.close()
        if not data.startswith(b"%PDF"):
            raise SignError("pdf_url did not return a PDF (missing %PDF header)", 400)
        return data
    raise SignError("pdf_url redirect limit exceeded", 400)


def materialize_pdf(*, pdf_path: str | None = None, pdf_base64: str | None = None,
                    pdf_url: str | None = None, document_name: str | None = None) -> str:
    """Resolve one of pdf_path / pdf_base64 / pdf_url to a local filesystem path."""
    path = (pdf_path or "").strip() or None
    b64 = (pdf_base64 or "").strip() or None
    url = (pdf_url or "").strip() or None
    n = sum(1 for x in (path, b64, url) if x)
    if n == 0:
        raise SignError("Provide pdf_path, pdf_base64, or pdf_url", 400)
    if n > 1:
        raise SignError("Provide only one of pdf_path, pdf_base64, or pdf_url", 400)
    if path:
        return path
    data = _decode_pdf_base64(b64) if b64 else _fetch_pdf_url(url)  # type: ignore[arg-type]
    name = (document_name or "document").strip() or "document"
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in name)[:80] or "document"
    if not safe.lower().endswith(".pdf"):
        safe += ".pdf"
    dest_dir = get_settings().data_dir / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{secrets.token_hex(8)}-{safe}"
    dest.write_bytes(data)
    return str(dest)


def register_download(path: str, *, name: str | None = None, ttl: int = DOWNLOAD_TTL_SECONDS) -> dict[str, Any]:
    """Create a one-time-ish download token for a local file; returns token metadata."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise SignError(f"file not found for download: {path}", 404)
    token = secrets.token_urlsafe(24)
    data = p.read_bytes()
    rec = {
        "path": str(p.resolve()),
        "name": name or p.name,
        "expires": time.time() + max(60, ttl),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }
    with _lock:
        _downloads[token] = rec
        # prune expired
        now = time.time()
        dead = [k for k, v in _downloads.items() if v["expires"] < now]
        for k in dead:
            _downloads.pop(k, None)
    return {"token": token, **{k: rec[k] for k in ("name", "expires", "sha256", "size")}}


def pop_download(token: str) -> dict[str, Any] | None:
    with _lock:
        rec = _downloads.get(token)
        if rec is None:
            return None
        if time.time() > rec["expires"]:
            _downloads.pop(token, None)
            return None
        return rec


def attach_cloud_result(result: dict) -> dict:
    """If HTTP mode and result has signed_pdf_path, add download URL (+ base64 if small)."""
    if not http_mode_active():
        return result
    path = result.get("signed_pdf_path")
    if not path or not Path(str(path)).is_file():
        # also check nested final_status
        fs = result.get("final_status")
        if isinstance(fs, dict) and fs.get("signed_pdf_path"):
            path = fs["signed_pdf_path"]
        else:
            return result
    try:
        meta = register_download(str(path))
    except SignError:
        return result
    base = get_http_public_base()
    url = f"{base}/download/{meta['token']}" if base else f"/download/{meta['token']}"
    result["signed_pdf_url"] = url
    result["signed_pdf_save_url"] = url + "?save=1"
    result["signed_pdf_url_expires_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(meta["expires"]))
    result["signed_pdf_sha256"] = meta["sha256"]
    result["signed_pdf_bytes"] = meta["size"]
    # Honest wording for the agent
    note = ("Download link is served by the user's local gotoquill through their tunnel; "
            "the PDF stays on their device. The link expires and requires the MCP session "
            "bearer (Authorization: Bearer …) or the download token in the path. "
            "Offer signed_pdf_save_url to people on phones or tablets for Share and Save to Files.")
    result["signed_pdf_delivery"] = note
    if meta["size"] <= BASE64_RETURN_MAX:
        result["signed_pdf_base64"] = base64.b64encode(Path(str(path)).read_bytes()).decode("ascii")
    if result.get("next") and "signed_pdf_path" in str(result.get("next")):
        result["next"] = (str(result["next"]) + f" Also give the user signed_pdf_url ({url}) so they can "
                          "download the signed PDF from their own machine via the tunnel. On phones or tablets, "
                          "offer signed_pdf_save_url for Share and Save to Files.")
    return result


def reset_downloads() -> None:
    with _lock:
        _downloads.clear()
