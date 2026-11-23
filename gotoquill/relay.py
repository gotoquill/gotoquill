"""Relays for "sealed link" mode: a dumb public mailbox that only ever sees ciphertext.

Default for local/desktop: ntfy.sh (no account).
For cloud agents (Muse etc.): use the open-source gotoquill relay (`GOTOQUILL_RELAY_TYPE=gotoquill`
or `GOTOQUILL_CLOUD=1`) and set `GOTOQUILL_RELAY_URL` to **your** Worker. There is no shared
public relay. each user deploys on their own Cloudflare account (free, one command; see
relay/README.md / relay/cloudflare/deploy.sh).

Override with GOTOQUILL_RELAY_URL / GOTOQUILL_RELAY. Topics are random 32-byte names.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from typing import Protocol
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DEFAULT_RELAY_URL = "https://ntfy.sh"
DEFAULT_PAGE_URL = "https://example.github.io/gotoquill/"
MAX_PAYLOAD_BYTES = 15 * 1024 * 1024          # ntfy.sh attachment cap
GOTOQUILL_MAX_PAYLOAD_BYTES = 1 * 1024 * 1024  # gotoquill relay ~1 MiB (strict defaults)
USER_AGENT = "gotoquill"
# Shown by Workers/Python when DEMO=1 (private/testing deploys). Not a shared public service.
DEMO_NOTICE = (
    "demo / for testing only, no uptime guarantee, may be rate limited or shut down at any time; "
    "deploy your own for production"
)
MISSING_GOTOQUILL_RELAY = (
    "GOTOQUILL_RELAY_URL is required for the gotoquill relay "
    "(cloud mode / GOTOQUILL_RELAY_TYPE=gotoquill). "
    "There is no shared public relay. deploy your own on your Cloudflare account (free, one command): "
    "cd relay/cloudflare && ./deploy.sh "
    "(or the Deploy to Cloudflare button in relay/README.md), then "
    "export GOTOQUILL_RELAY_URL=https://<your-worker>.<subdomain>.workers.dev "
    "and GOTOQUILL_RELAY_TYPE=gotoquill."
)


class RelayError(Exception):
    pass


def cloud_mode() -> bool:
    """True when running for a cloud assistant (tunnel / remote MCP / explicit flag)."""
    from .envcompat import env_bool
    return env_bool("CLOUD", False)


def relay_type(base_url: str | None = None) -> str:
    """'ntfy' or 'gotoquill'. Explicit GOTOQUILL_RELAY_TYPE (or deprecated AGENT_SIGN_RELAY_TYPE) wins;
    cloud mode prefers gotoquill. Deprecated alias: agentsign."""
    from .envcompat import env_get
    t = (env_get("RELAY_TYPE") or "").strip().lower()
    if t in ("agentsign", "agent-sign"):
        t = "gotoquill"
    if t in ("ntfy", "gotoquill"):
        return t
    if base_url is None and cloud_mode():
        return "gotoquill"
    url = (base_url or env_get("RELAY") or env_get("RELAY_URL")
           or DEFAULT_RELAY_URL).rstrip("/")
    host = (urlparse(url).hostname or "").lower()
    path = (urlparse(url).path or "").lower()
    if any(x in host for x in ("gotoquill-relay", "agent-sign-relay", "agentsign-relay")) or "/v1" in path:
        return "gotoquill"
    return "ntfy"


def relay_url() -> str:
    """Resolve relay base URL. gotoquill requires an explicit GOTOQUILL_RELAY_URL (no shared default)."""
    from .envcompat import env_get
    explicit = (env_get("RELAY") or env_get("RELAY_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    if relay_type() == "gotoquill":
        raise RelayError(MISSING_GOTOQUILL_RELAY)
    return DEFAULT_RELAY_URL


def page_url() -> str:
    """Base URL of the static signing page (web/). GOTOQUILL_PAGE_BASE (or legacy PAGE_URL /
    AGENT_SIGN_* equivalents) lets forks and self-hosters point at their own copy."""
    from .envcompat import env_get
    u = (env_get("PAGE_BASE") or env_get("PAGE_URL") or DEFAULT_PAGE_URL).strip()
    return u if u.endswith("/") else u + "/"


_PAGE_OK: dict[str, tuple[bool, float]] = {}
PAGE_CHECK_TTL = 600.0


def page_reachable(url: str | None = None, timeout: float = 3.0) -> bool:
    """True if the hosted signing page answers 2xx/3xx. Cached per URL (10 min).
    GOTOQUILL_PAGE_CHECK=0 skips the check (assume reachable)."""
    from .envcompat import env_get
    if (env_get("PAGE_CHECK") or "1").lower() in ("0", "false", "no", "off"):
        return True
    url = url or page_url()
    hit = _PAGE_OK.get(url)
    if hit and time.monotonic() - hit[1] < PAGE_CHECK_TTL:
        return hit[0]
    ok = False
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https page URL
                ok = 200 <= resp.status < 400
            break
        except urllib.error.HTTPError as e:
            if e.code == 405 and method == "HEAD":
                continue
            ok = False
            break
        except Exception:  # noqa: BLE001 - offline, DNS, timeout
            ok = False
            break
    _PAGE_OK[url] = (ok, time.monotonic())
    return ok


def new_topic() -> str:
    """Random topic (≥128 bits of entropy). 32 bytes → 43 url-safe chars; fits ntfy's 64-char limit."""
    return secrets.token_urlsafe(32)


def new_topic_128() -> str:
    """Exactly 128-bit topic (16 bytes → 22 url-safe chars). Prefer new_topic() for ntfy compatibility."""
    return secrets.token_urlsafe(16)


# ---------------------------------------------------------------- crypto (AES-256-GCM, same as WebCrypto)
def aad(kind: str, topic: str) -> bytes:
    return f"gotoquill/sealed/v1|{kind}|{topic}".encode()


def seal(key: bytes, plaintext: bytes, ad: bytes) -> bytes:
    iv = secrets.token_bytes(12)
    return iv + AESGCM(key).encrypt(iv, plaintext, ad)


def unseal(key: bytes, blob: bytes, ad: bytes) -> bytes:
    if len(blob) < 12 + 16:
        raise RelayError("ciphertext too short")
    return AESGCM(key).decrypt(blob[:12], blob[12:], ad)


# ---------------------------------------------------------------- relay interface
class Relay(Protocol):
    base_url: str
    kind: str

    def publish(self, topic: str, data: bytes, filename: str = "payload.bin") -> dict: ...

    def fetch(self, topic: str) -> list[bytes]: ...


class NtfyRelay:
    """Minimal ntfy client (stdlib only) with retries."""

    kind = "ntfy"

    def __init__(self, base_url: str | None = None, timeout: float = 30, retries: int = 3):
        self.base_url = (base_url or relay_url()).rstrip("/")
        self.timeout, self.retries = timeout, retries

    def _req(self, method: str, url: str, data: bytes | None = None, headers: dict | None = None) -> bytes:
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, data=data, method=method,
                                             headers={"User-Agent": USER_AGENT, **(headers or {})})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.read(MAX_PAYLOAD_BYTES + 1)
            except urllib.error.HTTPError as e:
                last = e
                if e.code < 500 and e.code != 429:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = e
            time.sleep(0.5 * 2 ** attempt)
        raise RelayError(f"relay {self.base_url} not reachable: {last}")

    def publish(self, topic: str, data: bytes, filename: str = "payload.bin") -> dict:
        if len(data) > MAX_PAYLOAD_BYTES:
            raise RelayError("encrypted payload is larger than 15 MB; use delivery='file' or a smaller PDF")
        raw = self._req("PUT", f"{self.base_url}/{topic}", data,
                        {"Filename": filename, "Content-Type": "application/octet-stream"})
        try:
            return json.loads(raw)
        except ValueError:
            return {}

    def fetch(self, topic: str) -> list[bytes]:
        """All messages cached on a topic, oldest first: attachment bytes, or base64-decoded message text."""
        raw = self._req("GET", f"{self.base_url}/{topic}/json?poll=1&since=all")
        out: list[bytes] = []
        for line in raw.decode("utf-8", "replace").splitlines():
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("event") != "message":
                continue
            att = m.get("attachment") or {}
            try:
                if att.get("url"):
                    if int(att.get("size") or 0) > MAX_PAYLOAD_BYTES:
                        continue
                    out.append(self._req("GET", att["url"]))
                elif m.get("message"):
                    out.append(base64.b64decode(m["message"] + "=" * (-len(m["message"]) % 4), altchars=b"-_"))
            except (RelayError, ValueError):
                continue
        return out


class GotoquillRelay:
    """Client for the gotoquill zero-knowledge relay (PUT/GET /v1/box/<topic>, delete-on-read)."""

    kind = "gotoquill"

    def __init__(self, base_url: str | None = None, timeout: float = 30, retries: int = 3):
        self.base_url = (base_url or relay_url()).rstrip("/")
        self.timeout, self.retries = timeout, retries

    def _box(self, topic: str) -> str:
        return f"{self.base_url}/v1/box/{topic}"

    def _req(self, method: str, url: str, data: bytes | None = None, headers: dict | None = None,
             *, allow_404: bool = False) -> bytes | None:
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, data=data, method=method,
                                             headers={"User-Agent": USER_AGENT, **(headers or {})})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.read(GOTOQUILL_MAX_PAYLOAD_BYTES + 1)
            except urllib.error.HTTPError as e:
                if allow_404 and e.code == 404:
                    return None
                last = e
                if e.code < 500 and e.code != 429:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = e
            time.sleep(0.5 * 2 ** attempt)
        raise RelayError(f"relay {self.base_url} not reachable: {last}")

    def publish(self, topic: str, data: bytes, filename: str = "payload.bin") -> dict:
        if len(data) > GOTOQUILL_MAX_PAYLOAD_BYTES:
            raise RelayError("encrypted payload is larger than 1 MiB; use delivery='file' or a smaller PDF")
        raw = self._req("PUT", self._box(topic), data,
                        {"Content-Type": "application/octet-stream", "X-TTL-Seconds": "3600"})
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {"ok": True}

    def fetch(self, topic: str) -> list[bytes]:
        """At most one blob (delete-on-read). Empty list if nothing is waiting.

        Uses HEAD first so empty polls stay on the cheap exists path (no body, tiny KV marker).
        """
        if not self.exists(topic):
            return []
        raw = self._req("GET", self._box(topic), allow_404=True)
        if raw is None:
            return []
        if len(raw) > GOTOQUILL_MAX_PAYLOAD_BYTES:
            return []
        return [raw]

    def exists(self, topic: str) -> bool:
        """HEAD without consuming (signing page 'already answered' check)."""
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(self._box(topic), method="HEAD",
                                             headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return 200 <= r.status < 300
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return False
                last = e
                if e.code < 500 and e.code != 429:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = e
            time.sleep(0.5 * 2 ** attempt)
        raise RelayError(f"relay {self.base_url} not reachable: {last}")


class MemoryRelay:
    """In-process fake relay for tests. Records everything it was given (to prove it only saw ciphertext)."""

    kind = "memory"

    def __init__(self, base_url: str = "https://relay.test"):
        self.base_url = base_url
        self.topics: dict[str, list[bytes]] = {}

    def publish(self, topic: str, data: bytes, filename: str = "payload.bin") -> dict:
        self.topics.setdefault(topic, []).append(bytes(data))
        return {"id": secrets.token_hex(6), "topic": topic}

    def fetch(self, topic: str) -> list[bytes]:
        return list(self.topics.get(topic, []))

    def exists(self, topic: str) -> bool:
        return bool(self.topics.get(topic))


_relay: Relay | None = None


def make_relay(base_url: str | None = None) -> Relay:
    url = (base_url or relay_url()).rstrip("/")
    if relay_type(url) == "gotoquill":
        return GotoquillRelay(url)
    return NtfyRelay(url)


AgentSignRelay = GotoquillRelay  # deprecated alias


def get_relay() -> Relay:
    return _relay or make_relay()


def set_relay(r: Relay | None) -> None:
    global _relay
    _relay = r
