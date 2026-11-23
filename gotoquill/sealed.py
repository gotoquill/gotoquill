"""Sealed-link signing (the default delivery).

The agent encrypts everything the signing page needs (page images, the PDF, placements, request id, document
SHA-256, a per-request HMAC key) with a fresh AES-256-GCM key, and uploads only that ciphertext to a public
relay (ntfy.sh or the gotoquill relay) under a random topic. The human gets a link to a static page (GitHub Pages or any host):

    https://<page>/#v=1&q=<request topic>&a=<reply topic>&k=<key>[&r=<relay url>][&rt=gotoquill]

Everything after '#' stays in the browser (never sent to the page host). The page downloads the ciphertext,
decrypts it, shows the document, lets the human sign, encrypts the reply with the same key and posts it to the
reply topic. get_signature_status() pulls the reply, decrypts it, checks request id / document hash / HMAC
proof / expiry / one-time use (shared with file mode) and stamps the PDF (pypdf + reportlab).
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import threading
import time
from pathlib import Path
from urllib.parse import quote

from . import notify, offline, relay
from .core import SignError

DELIVERY = "sealed link via relay"
DEFAULT_TTL_MINUTES = 60
MAX_TTL_MINUTES = 180  # ntfy.sh keeps attachments ~3 hours
_lock = threading.Lock()


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def build_link(page: str, req_topic: str, reply_topic: str, key: bytes, relay_base: str,
               relay_kind: str | None = None) -> str:
    frag = f"v=1&q={req_topic}&a={reply_topic}&k={_b64u(key)}"
    kind = relay_kind or relay.relay_type(relay_base)
    if relay_base.rstrip("/") != relay.DEFAULT_RELAY_URL:
        frag += "&r=" + quote(relay_base, safe="")
    if kind == "gotoquill":
        frag += "&rt=gotoquill"
    return page.split("#", 1)[0] + "#" + frag


_PKG_WEB = Path(__file__).resolve().parent / "web"  # installed wheel: web/ is force-included here
WEB_DIR = _PKG_WEB if (_PKG_WEB / "sign.js").is_file() else Path(__file__).resolve().parent.parent / "web"


def build_sealed_html(fragment: str) -> str:
    """One self-contained signing page: web/index.html with sign.js inlined and the link params embedded.

    The CSP allows exactly these two inline scripts (by SHA-256 hash), nothing else."""
    import hashlib
    page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    js = (WEB_DIR / "sign.js").read_text(encoding="utf-8").replace("</", "<\\/")
    boot = "window.GOTOQUILL_SEALED=" + json.dumps(fragment) + ";"
    h = lambda t: "'sha256-" + base64.b64encode(hashlib.sha256(t.encode()).digest()).decode() + "'"
    if '<script src="sign.js"></script>' not in page or "script-src 'self'" not in page:
        raise SignError("web/index.html layout changed; cannot build the sealed file", 500)
    page = page.replace("script-src 'self'", f"script-src {h(boot)} {h(js)}")
    return page.replace('<script src="sign.js"></script>', f"<script>{boot}</script>\n<script>{js}</script>")


def qr_files(link: str, png_path: Path) -> tuple[str | None, str | None]:
    try:
        import segno
    except ImportError:
        return None, None
    q = segno.make(link, error="l")
    q.save(str(png_path), scale=6, border=3)
    buf = io.StringIO()
    q.terminal(out=buf, compact=True, border=2)
    return str(png_path), buf.getvalue()


def create_sealed_request(*, pdf_path: str, expires_in_minutes: int | None = None, as_file: bool = False,
                          html_path: str | None = None, **kw) -> dict:
    import secrets
    r = relay.get_relay()
    key = secrets.token_bytes(32)
    req_topic, reply_topic = relay.new_topic(), relay.new_topic()
    d, page_data, pages, pdf_bytes = offline.prepare_request(
        pdf_path=pdf_path, expires_in_minutes=expires_in_minutes, delivery=DELIVERY,
        default_ttl=DEFAULT_TTL_MINUTES, max_ttl=MAX_TTL_MINUTES, page_width_px=1000, **kw)
    rid = d["request_id"]
    payload = {"type": "gotoquill-sealed-request", "version": 1, "data": page_data, "pages": pages,
               "placements": d["placements"], "pdf_base64": base64.b64encode(pdf_bytes).decode(),
               "document_sha256": d["original_sha256"]}
    blob = relay.seal(key, json.dumps(payload).encode(), relay.aad("request", req_topic))
    if len(blob) > relay.MAX_PAYLOAD_BYTES:  # drop the PDF copy first (the page only needs the images)
        payload["pdf_base64"] = None
        blob = relay.seal(key, json.dumps(payload).encode(), relay.aad("request", req_topic))
    try:
        r.publish(req_topic, blob, "request.bin")
    except relay.RelayError as e:
        d["status"] = "cancelled"
        offline._store(d)
        raise SignError(f"could not upload to the relay: {e}. Try delivery='file' instead.", 502) from e
    page_base = relay.page_url()
    link = build_link(page_base, req_topic, reply_topic, key, r.base_url,
                      relay_kind=getattr(r, "kind", None))
    fallback = False
    if not as_file and not relay.page_reachable(page_base):
        as_file, fallback = True, True  # hosted page down (private repo, Pages off): ship the self-contained file
    if as_file:
        hp = (Path(html_path).expanduser().resolve() if html_path
              else Path(pdf_path).expanduser().resolve().with_name(f"{d['friendly_name']} - sign.html"))
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(build_sealed_html(link.split("#", 1)[1]), encoding="utf-8")
        d["html_path"] = str(hp)
    qr_png, qr_ascii = qr_files(link, offline._dir(rid) / "qr.png")
    d.update(sealed={"relay": r.base_url, "relay_type": getattr(r, "kind", relay.relay_type(r.base_url)),
                     "request_topic": req_topic, "reply_topic": reply_topic,
                     "key": _b64u(key), "payload_bytes": len(blob)}, sign_url=link)
    offline._store(d)
    out = {
        "request_id": rid, "status": "pending", "delivery": DELIVERY, "sign_url": link,
        "qr_png_path": qr_png, "qr_ascii": qr_ascii, "expires_at": d["expires_at"],
        "document_sha256": d["original_sha256"], "output_path": d["output_path"], "audit_path": d["audit_path"],
        "placements": d["placements"], "wait_command": notify.wait_command(rid),
        "next": ("Send the user this link (or show the QR code). It opens a signing page on any phone or computer: "
                 f"{link}  It works once and expires {d['expires_at']}. Only encrypted data passes through the relay "
                 f"({r.base_url}). Then " + notify.wake_guidance(rid)),
    }
    if as_file:
        out.update(delivery=DELIVERY + " (sealed file)", html_path=d["html_path"],
                   next=(f"Send the user this one file: {d['html_path']}. They open it in a browser (it needs internet), "
                         "review and sign; the encrypted reply goes back via the relay. The file holds the decryption key: "
                         "send it only to the signer. Then " + notify.wake_guidance(rid)))
    if fallback:
        out.update(sign_url=None, qr_png_path=None, qr_ascii=None, link_fallback=True,
                   warning=f"The hosted signing page {page_base} is not reachable, so no link was made. "
                           "Use the self-contained HTML file instead (set GOTOQUILL_PAGE_BASE to your own copy of web/).",
                   next=(f"The signing link page is unavailable, so do NOT send a link. Send the signer this one file "
                         f"instead: {d['html_path']} (attach it to email/chat; it holds the key, so send it only to "
                         "them). They open it in a browser, review and sign. Then " + notify.wake_guidance(rid)))
    return offline.with_preview(out, d)


def _key(d: dict) -> bytes:
    k = d["sealed"]["key"]
    return base64.urlsafe_b64decode(k + "=" * (-len(k) % 4))


def check_reply(request_id: str) -> dict | None:
    """Pull the reply topic once; apply the first valid reply. Returns the apply result or None.

    For the gotoquill relay, probe with HEAD (exists) first so empty polls do not
    consume a GET / KV delete-on-read path.
    """
    d = offline._load(request_id)
    if d["status"] != "pending" or "sealed" not in d:
        return None
    s = d["sealed"]
    try:
        r = relay.get_relay()
        # Cheap existence check when the relay supports it (GotoquillRelay HEAD).
        exists = getattr(r, "exists", None)
        if callable(exists) and not exists(s["reply_topic"]):
            return None
        msgs = r.fetch(s["reply_topic"])
    except relay.RelayError:
        return None  # transient; try again next poll
    last_err: SignError | None = None
    for blob in msgs:
        try:
            obj = json.loads(relay.unseal(_key(d), blob, relay.aad("reply", s["reply_topic"])))
        except Exception:  # noqa: BLE001 - junk or forged messages on the topic are ignored
            continue
        try:
            res = offline.apply_signature_response(request_id, response_obj=obj)
        except SignError as e:
            last_err = e
            continue
        d = offline._load(request_id)
        d["sealed"]["abandoned"] = True  # ntfy has no delete; topics are random and expire on their own
        d["sealed"]["key"] = None  # forget the key: nothing more can be decrypted or accepted
        d["sign_url"] = None
        offline._store(d)
        return res
    if last_err is not None:
        return {"request_id": request_id, "status": "pending", "warning": f"a reply was rejected: {last_err}"}
    return None


@contextlib.contextmanager
def _file_lock(request_id: str):
    """Several pollers (the agent, `gotoquill wait`, the watcher) may run in different processes: only one may
    pull and apply the reply at a time, so the PDF is stamped once."""
    try:
        import fcntl
    except ImportError:  # Windows: the in-process lock + the 'already applied' check still apply
        yield
        return
    with open(offline._dir(request_id) / ".poll.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def status(request_id: str, wait_seconds: float = 0) -> dict:
    """Poll the relay for a reply. Sleeps ~5s growing to 30s+ so cloud agents (Muse)
    can run wait_for_signature / gotoquill wait without burning free-tier Worker/KV quotas."""
    deadline = time.monotonic() + max(0.0, min(float(wait_seconds or 0), 600))
    warn = None
    attempt = 0
    while True:
        st = offline.status(request_id)
        if st["status"] != "pending":
            break
        with _lock, _file_lock(request_id):
            res = check_reply(request_id)
        if res and res.get("status") != "pending":
            st = offline.status(request_id)
            break
        if res and res.get("warning"):
            warn = res["warning"]
        if time.monotonic() >= deadline:
            break
        # 5s, ~7.5s, ~11s, … growing to 30s+ (caps at 45s)
        delay = min(45.0, 5.0 * (1.5 ** min(attempt, 8)))
        attempt += 1
        time.sleep(min(delay, max(0.1, deadline - time.monotonic())))
    if warn and st["status"] == "pending":
        st["warning"] = warn
    return st


def is_sealed(request_id: str) -> bool:
    try:
        return offline.exists(request_id) and "sealed" in offline._load(request_id)
    except SignError:
        return False


def cancel(request_id: str) -> dict:
    return offline.cancel(request_id)
