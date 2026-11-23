"""Saved notify targets ("wake the agent when it's signed") and authenticated webhook delivery.

Store: <config dir>/notify-targets.json, permissions 0600. Encrypted (Fernet) with a random key in the OS keychain
(same code path as saved signatures) when one is available; otherwise a plain 0600 file.
It holds the local HMAC secret (X-Gotoquill-Signature) and the targets added by `gotoquill connect`.

Header values may be literals (kept only in this store) or "env:VAR" references, resolved when the hook fires,
so a secret can stay in the environment and never touch disk. Nothing here is ever printed unmasked.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from typing import Any

KEYRING_USER = "notify-targets-key"
KINDS = ("webhook", "openclaw", "telegram")
_lock = threading.Lock()
_HDR = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,100}$")
_ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,100}$")
_RESERVED = {"content-type", "content-length", "host", "x-gotoquill-signature", "x-gotoquill-timestamp"}


class TargetError(ValueError):
    pass


# ------------------------------------------------------------------ store
def store_path():
    from .vault import config_dir
    return config_dir() / "notify-targets.json"


def _load() -> dict:
    p = store_path()
    if not p.exists():
        return {"targets": []}
    raw = json.loads(p.read_text(encoding="utf-8"))
    if raw.get("encrypted"):
        from .vault import _get_key
        key = _get_key(create=False, user=KEYRING_USER)
        if not key:
            raise TargetError("notify targets are encrypted but the OS keychain key is not available")
        from cryptography.fernet import Fernet
        return json.loads(Fernet(key).decrypt(raw["data"].encode()))
    return raw.get("store", {"targets": []})


def _save(doc: dict) -> None:
    from .vault import KEYRING_SERVICE, _get_key, _write
    key = _get_key(create=True, user=KEYRING_USER)
    if key:
        from cryptography.fernet import Fernet
        out = {"version": 1, "encrypted": True, "key_location": f"OS keychain ({KEYRING_SERVICE}/{KEYRING_USER})",
               "data": Fernet(key).encrypt(json.dumps(doc).encode()).decode()}
    else:
        out = {"version": 1, "encrypted": False, "note": "No OS keychain found; protected by file permissions 0600.",
               "store": doc}
    _write(store_path(), json.dumps(out, indent=1))


def secret(create: bool = True) -> str | None:
    """The local HMAC secret (secrets.token_urlsafe(32)), created on first use."""
    with _lock:
        d = _load()
        if not d.get("secret") and create:
            d["secret"] = secrets.token_urlsafe(32)
            _save(d)
        return d.get("secret")


def targets() -> list[dict]:
    try:
        return list(_load().get("targets", []))
    except Exception:  # noqa: BLE001  (unreadable store: behave as if none)
        return []


def add(t: dict) -> dict:
    t = validate(t)
    with _lock:
        d = _load()
        d.setdefault("secret", secrets.token_urlsafe(32))
        d["targets"] = [x for x in d.get("targets", []) if x.get("id") != t["id"]] + [t]
        _save(d)
    return t


def remove(target_id: str | None) -> list[str]:
    """Remove one target by id, or everything (targets + secret) when target_id is None/'all'."""
    with _lock:
        p = store_path()
        if not p.exists():
            return []
        try:
            d = _load()
        except Exception:  # noqa: BLE001
            p.unlink()
            return ["(unreadable store)"]
        if target_id in (None, "", "all"):
            p.unlink()
            return [x["id"] for x in d.get("targets", [])]
        keep = [x for x in d.get("targets", []) if x.get("id") != target_id]
        gone = [x["id"] for x in d.get("targets", []) if x.get("id") == target_id]
        d["targets"] = keep
        _save(d)
        return gone


# ------------------------------------------------------------------ validation / masking
def check_url(url: str, what: str = "webhook") -> str:
    u = str(url or "").strip()
    if not re.match(r"^https?://[^\s/]+", u, re.I):
        raise TargetError(f"{what} must be an http(s) URL")
    return u


def check_headers(h: dict | None) -> dict:
    out = {}
    for k, v in (h or {}).items():
        if not _HDR.match(str(k)) or str(k).lower() in _RESERVED:
            raise TargetError(f"header name not allowed: {k!r}")
        v = str(v)
        if any(c in v for c in "\r\n\0"):
            raise TargetError(f"header {k}: control characters not allowed")
        if v.startswith("env:") and not _ENV.match(v[4:]):
            raise TargetError(f"header {k}: env:VAR needs a valid variable name")
        out[str(k)] = v
    return out


def check_body(b: Any) -> Any:
    if b is None or b == "":
        return None
    if isinstance(b, str):
        try:
            b = json.loads(b)
        except ValueError as e:
            raise TargetError("body template must be JSON") from e
    if not isinstance(b, (dict, list)):
        raise TargetError("body template must be a JSON object or array")
    return b


def validate(t: dict) -> dict:
    kind = t.get("kind")
    if kind not in KINDS:
        raise TargetError(f"kind must be one of {KINDS}")
    t = dict(t)
    t["id"] = re.sub(r"[^a-z0-9_-]", "-", str(t.get("id") or kind).lower())[:40]
    if kind in ("webhook", "openclaw"):
        t["url"] = check_url(t.get("url"))
        t["headers"] = check_headers(t.get("headers"))
        t["body"] = check_body(t.get("body"))
    if kind == "telegram":
        if not _ENV.match(str(t.get("bot_token_env") or "")):
            raise TargetError("telegram needs bot_token_env (the NAME of an env var holding the bot token)")
        if not re.fullmatch(r"-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{3,31}", str(t.get("chat_id") or "")):
            raise TargetError("telegram chat_id must be a numeric id or @channelname")
    return t


def mask_value(v: str) -> str:
    v = str(v)
    return v if v.startswith("env:") else "***"


def mask_url(u: str) -> str:
    m = re.match(r"^(https?://[^/?#]+)(.*)$", str(u or ""))
    if not m:
        return "***"
    return m.group(1) + ("/…" if m.group(2) not in ("", "/") else "")


def public(t: dict) -> dict:
    """Safe to show: no secret values (header literals, tokens, URL paths that may embed keys)."""
    out = {"id": t["id"], "kind": t["kind"]}
    if t.get("url"):
        out["url"] = mask_url(t["url"])
    if t.get("headers"):
        out["headers"] = {k: mask_value(v) for k, v in t["headers"].items()}
    if t.get("body") is not None:
        out["body_template"] = True
    for k in ("bot_token_env", "chat_id", "config_path", "action", "added_at"):
        if t.get(k):
            out[k] = t[k]
    if t.get("token"):
        out["token"] = "***"
    return out


def status() -> dict:
    p = store_path()
    out = {"path": str(p), "exists": p.exists(), "targets": []}
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            out["encrypted"] = bool(raw.get("encrypted"))
            d = _load()
            out["targets"] = [public(t) for t in d.get("targets", [])]
            out["hmac_secret"] = "set" if d.get("secret") else "not set"
        except Exception as e:  # noqa: BLE001
            out["error"] = f"cannot read: {type(e).__name__}"
    return out


# ------------------------------------------------------------------ rendering / signing / sending
def wake_text(st: dict, rid: str) -> str:
    s, doc = st.get("status"), st.get("document_name") or "the document"
    if st.get("event") == "test":
        return "gotoquill test ping: signing notifications are connected. No action needed."
    if s == "completed":
        pdf = st.get("signed_pdf_path") or st.get("output_path") or ""
        return (f"gotoquill: {doc} was signed (request {rid}). Signed PDF: {pdf}. Send the signed file back to the "
                f"signer in the chat now (attach the file), with the preview {st.get('signed_preview_png_path') or ''}.")
    return f"gotoquill: signature request {rid} for {doc} is {s}."


def _ctx(st: dict, rid: str) -> dict:
    return {"request_id": rid, "status": str(st.get("status") or ""), "document_name": str(st.get("document_name") or ""),
            "signed_pdf_path": str(st.get("signed_pdf_path") or ""), "audit_path": str(st.get("audit_path") or ""),
            "signed_preview_png_path": str(st.get("signed_preview_png_path") or ""),
            "next": str(st.get("next") or ""), "message": wake_text(st, rid)}


def render_body(template: Any, st: dict, rid: str) -> bytes:
    """Template placeholders: {{request_id}} {{status}} {{document_name}} {{signed_pdf_path}} {{audit_path}}
    {{signed_preview_png_path}} {{next}} {{message}}; a string that is exactly "{{status_json}}" becomes the whole
    status object. No template: the status JSON itself."""
    if template is None:
        return json.dumps(st, default=str).encode()
    c = _ctx(st, rid)

    def walk(x):
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str):
            if x.strip() == "{{status_json}}":
                return json.loads(json.dumps(st, default=str))
            return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: c.get(m.group(1), m.group(0)), x)
        return x
    return json.dumps(walk(template), default=str).encode()


def resolve_headers(h: dict | None) -> tuple[dict, list[str]]:
    """env:VAR values are read now (fire time). Returns (headers, missing env var names)."""
    out, missing = {}, []
    for k, v in (h or {}).items():
        if str(v).startswith("env:"):
            val = os.environ.get(v[4:])
            if not val:
                missing.append(v[4:])
                continue
            out[k] = val
        else:
            out[k] = v
    return out, missing


def sign(body: bytes, ts: str, key: str) -> str:
    return "sha256=" + hmac.new(key.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify(body: bytes, ts: str, signature: str, key: str, max_age: float = 300) -> bool:
    """For receivers: check X-Gotoquill-Signature / X-Gotoquill-Timestamp."""
    try:
        if abs(time.time() - int(ts)) > max_age:
            return False
    except ValueError:
        return False
    return hmac.compare_digest(sign(body, ts, key), signature or "")


def _scrub(text: str, secrets_: list[str]) -> str:
    for s in secrets_:
        if s and len(s) >= 4:
            text = text.replace(s, "***")
    return text


def post(url: str, body: bytes, headers: dict, rid: str, st_status: str, timeout: float = 20) -> dict:
    ts = str(int(time.time()))
    h = {"Content-Type": "application/json", "User-Agent": "gotoquill", "X-Gotoquill-Request": rid,
         "X-Gotoquill-Status": st_status, "X-Gotoquill-Timestamp": ts}
    key = secret(create=True)
    if key:
        h["X-Gotoquill-Signature"] = sign(body, ts, key)
    h.update(headers)
    hidden = [v for v in headers.values()] + [key or "", url]
    try:
        req = urllib.request.Request(url, data=body, method="POST", headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - user-chosen URL
            return {"ok": 200 <= r.status < 300, "http_status": r.status}
    except urllib.error.HTTPError as e:
        return {"ok": False, "http_status": e.code}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": _scrub(f"{type(e).__name__}: {e}", hidden)}


def deliver(t: dict, st: dict, rid: str) -> dict:
    """Send one target. The result never contains secret values."""
    kind = t.get("kind")
    res: dict = {"id": t.get("id"), "kind": kind}
    try:
        if kind == "telegram":
            tok = os.environ.get(t["bot_token_env"], "")
            if not tok:
                return {**res, "ok": False, "error": f"env var {t['bot_token_env']} is not set"}
            body = json.dumps({"chat_id": t["chat_id"], "text": wake_text(st, rid)}).encode()
            url = f"https://api.telegram.org/bot{tok}/sendMessage"
            r = post(url, body, {}, rid, str(st.get("status")))
            return {**res, **{k: (_scrub(v, [tok]) if isinstance(v, str) else v) for k, v in r.items()}}
        headers, missing = resolve_headers(t.get("headers"))
        if missing:
            res["missing_env"] = missing
        if kind == "openclaw":
            if t.get("token"):
                headers.setdefault("Authorization", "Bearer " + t["token"])
            tpl = t.get("body") or {"source": "gotoquill", "message": "{{message}}", "request_id": "{{request_id}}",
                                     "status": "{{status}}", "signed_pdf_path": "{{signed_pdf_path}}"}
        else:
            tpl = t.get("body")
        r = post(t["url"], render_body(tpl, st, rid), headers, rid, str(st.get("status")))
        return {**res, **r}
    except Exception as e:  # noqa: BLE001
        return {**res, "ok": False, "error": type(e).__name__}
