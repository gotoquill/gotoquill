"""No-connection signing ("file mode"): for when the agent and the human share no network path.

1. create_file_request() writes ONE self-contained HTML file (original PDF, request id, document hash, a
   per-request key). No scripts, fonts or images are loaded from anywhere; it works opened from a phone's
   Downloads / Files app.
2. The human signs in that file. It produces a small "signature response" (a .gotoquill JSON file, or a
   compact copy-and-paste code) that they send back through the chat.
3. apply_signature_response() checks it (request id, document hash, HMAC proof, expiry, one-time use)
   and stamps the PDF.

Pending state lives in the config dir (<config>/file-requests/<request_id>/), so it survives restarts.
The per-request key is inside the HTML file: whoever holds that file can sign *that* request (like a
one-time link), but a response can never be replayed against a different request or document.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import html as _html
import json
import os
import re
import secrets
import threading
import zlib
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from . import pdf
from .pdfdoc import Document
from .config import get_settings
from .core import SignError, _decode_png, _iso, _parse
from .local import default_output_paths

DELIVERY = "file via chat"
CODE_PREFIX = "GOTOQUILL1"
CODE_PREFIX_LEGACY = "AGENTSIGN1"
RESPONSE_TYPES = frozenset({"gotoquill-response", "agent-sign-response"})
DEFAULT_TTL_MINUTES = 7 * 24 * 60
MAX_TTL_MINUTES = 30 * 24 * 60
_lock = threading.Lock()


def state_root() -> Path:
    from .vault import config_dir
    p = config_dir() / "file-requests"
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
    return p


def signer_context(resp: dict) -> dict:
    """Signer's time zone / locale as reported by the signing page (display only; not part of the proof)."""
    tz = str(resp.get("signer_timezone") or "")[:64]
    if not re.fullmatch(r"[A-Za-z0-9_+\-/]{1,64}", tz):
        tz = ""
    try:
        off = int(resp.get("signer_utc_offset"))
        off = off if -840 <= off <= 840 else None
    except (TypeError, ValueError):
        off = None
    loc = str(resp.get("signer_locale") or "")[:35]
    if not re.fullmatch(r"[A-Za-z0-9\-_]{2,35}", loc):
        loc = ""
    return {"timezone": tz or None, "utc_offset_minutes": off, "locale": loc or None}


def _dir(rid: str) -> Path:
    if not re.fullmatch(r"req_[0-9a-f]{16}", rid or ""):
        raise SignError("unknown request_id", 404)
    return state_root() / rid


def _load(rid: str) -> dict:
    f = _dir(rid) / "state.json"
    if not f.exists():
        raise SignError("unknown request_id (no file-mode request with this id on this computer)", 404)
    return json.loads(f.read_text())


def _store(d: dict) -> None:
    f = _dir(d["request_id"]) / "state.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(f)


def friendly_name(document_name: str) -> str:
    """'sample_contract.pdf' -> 'Sample contract' (spaces, no underscores in user-facing file names)."""
    stem = re.sub(r"\.pdf$", "", document_name, flags=re.I)
    stem = re.sub(r"[_\s]+", " ", stem).strip(" .-") or "Document"
    stem = re.sub(r'[\\/:*?"<>|]+', " ", stem)
    return (stem[0].upper() + stem[1:])[:80]


def proof_message(rid: str, doc_sha: str, sig_sha: str, method: str, typed_name: str, signer_name: str,
                  client_ts: str) -> str:
    return "|".join(["gotoquill/v1", rid, doc_sha, sig_sha, method or "", typed_name or "", signer_name or "", client_ts or ""])


# ---------------------------------------------------------------- step 1
def prepare_request(*, pdf_path: str, output_path: str | None = None, signer_name: str | None = None,
                    document_name: str | None = None, placements: list[dict] | None = None, add_date: bool = False,
                    proof_line: bool = True, date_format: str | None = None,
                    message: str | None = None, expires_in_minutes: int | None = None, page_width_px: int = 1000,
                    delivery: str = DELIVERY, default_ttl: int = DEFAULT_TTL_MINUTES, max_ttl: int = MAX_TTL_MINUTES,
                    extra: dict | None = None, spots=None, return_to: str | None = None) -> tuple[dict, dict, list[str], bytes]:
    """Shared by file mode and sealed-link mode: checks the PDF, resolves placements and stores the pending state.
    Offline mode embeds the original PDF; sealed mode retains its page PNG transport.
    Returns (state, signer page data, sealed page PNGs as base64, original PDF bytes)."""
    s = get_settings()
    from .returnto import normalize as _rt
    return_to = _rt(return_to)
    if date_format is not None and date_format not in pdf.DATE_FORMATS:
        raise SignError("date_format must be DD/MM/YYYY, MM/DD/YYYY or YYYY-MM-DD")
    src = Path(pdf_path).expanduser()
    if not src.is_file():
        raise SignError(f"file not found: {pdf_path}", 404)
    data = src.read_bytes()
    if len(data) > s.max_pdf_bytes:
        raise SignError("PDF too large", 413)
    try:
        info = pdf.inspect_pdf(data, s.max_pages)
    except pdf.PdfError as e:
        raise SignError(str(e)) from e
    ttl = expires_in_minutes or default_ttl
    if not 1 <= ttl <= max_ttl:
        raise SignError(f"expires_in_minutes must be 1..{max_ttl}")
    from . import placement as _pl
    try:
        placements, pinfo = _pl.plan(data, placements, add_date=add_date, spots=spots)
    except ValueError as e:
        raise SignError(str(e)) from e
    boxes = []
    with Document.open(data) as doc:
        for p in placements:
            p.setdefault("kind", "signature")
            if p["kind"] not in {"signature", "initials", "date"}:
                raise SignError(f"unknown placement kind: {p['kind']}")
            if add_date and p["kind"] != "date":
                p.setdefault("add_date", True)
                p.setdefault("proof_line", bool(proof_line))
            if date_format:
                p.setdefault("date_format", str(date_format)[:40])
            try:
                idx, r = pdf.resolve_rect(doc, p)
            except (KeyError, TypeError, ValueError) as e:
                raise SignError(f"bad placement {p}: {e}") from e
        boxes = _pl.boxes(doc, placements)
        pages = ([base64.b64encode(pdf.render_page_png(data, i + 1, page_width_px)).decode()
                  for i in range(doc.page_count)] if delivery != DELIVERY else [])
    rid = "req_" + secrets.token_hex(8)
    key = secrets.token_hex(32)
    now = pdf.utcnow()
    expires = now + timedelta(minutes=ttl)
    doc_name = (document_name or src.name)[:200]
    nice = friendly_name(doc_name)
    out, audit = default_output_paths(str(src), output_path, rid)
    d = {
        "request_id": rid, "status": "pending", "delivery": delivery, "created_at": _iso(now), "expires_at": _iso(expires),
        "document_name": doc_name, "friendly_name": nice, "signer_name": (signer_name or None) and signer_name[:200],
        "message": (message or None) and message[:1000], "placements": placements, "page_count": info["page_count"],
        "original_sha256": pdf.sha256(data), "consent_text": s.consent_text, "key": key,
        "pdf_path": str(src.resolve()), "output_path": str(out), "audit_path": str(audit), "return_to": return_to,
    }
    if delivery == DELIVERY:
        d["stamp_plan"] = pdf.stamp_plan(data, placements)
    d.update(extra or {})
    rdir = _dir(rid)
    rdir.mkdir(mode=0o700)
    (rdir / "original.pdf").write_bytes(data)
    d["placement_info"] = pinfo
    d["preview_png_paths"] = _pl.preview_pngs(data, placements, rdir, nice)
    _store(d)
    page_data = {k: d[k] for k in ("request_id", "document_name", "signer_name", "message", "page_count",
                                   "original_sha256", "consent_text", "created_at", "expires_at")}
    page_data.update(return_to=return_to, key=key, response_name=f"{nice} signature", boxes=boxes, version=1)
    if delivery == DELIVERY:
        page_data.update(pdf_base64=base64.b64encode(data).decode(), stamp_plan=d["stamp_plan"],
                         signed_pdf_name=f"{nice} signed.pdf")
    return d, page_data, pages, data


def preview_fields(d: dict) -> dict:
    """Request-result fields describing where the signature goes (shared by all deliveries)."""
    paths = d.get("preview_png_paths") or []
    info = d.get("placement_info") or {}
    tip = ""
    if paths:
        tip = ("First show the user the preview image " + " and ".join(paths) + " (highlighted: where the signature"
               + (" and date" if any(p.get("kind") == "date" for p in d["placements"]) else "") + " will go)"
               + (" and tell them the placement is a guess" if info.get("guess") else "") + ". ")
    return {"placements": d["placements"], "placement_info": info,
            "preview_png_path": paths[0] if paths else None, "preview_png_paths": paths, "_preview_tip": tip}


def with_preview(out: dict, d: dict) -> dict:
    pf = preview_fields(d)
    tip = pf.pop("_preview_tip")
    out.update(pf)
    if out.get("next"):
        out["next"] = tip + out["next"]
    return out


def create_file_request(*, pdf_path: str, html_path: str | None = None, **kw: Any) -> dict:
    src = Path(pdf_path).expanduser()
    d, page_data, pages, _ = prepare_request(pdf_path=pdf_path, **kw)
    rid, nice, out, audit = d["request_id"], d["friendly_name"], d["output_path"], d["audit_path"]
    hp = Path(html_path).expanduser().resolve() if html_path else src.resolve().with_name(f"{nice} - sign.html")
    d["html_path"] = str(hp)
    _store(d)
    hp.parent.mkdir(parents=True, exist_ok=True)
    hp.write_text(render_html(page_data, pages, nice), encoding="utf-8")
    return with_preview({
        "request_id": rid, "status": "pending", "delivery": DELIVERY, "html_path": str(hp),
        "html_bytes": hp.stat().st_size, "expires_at": d["expires_at"], "document_sha256": d["original_sha256"],
        "output_path": str(out), "audit_path": str(audit), "placements": d["placements"],
        "next": (f"Send the user the file '{hp.name}' (attach it in the chat). They open it in any browser, sign, and "
                 f"download the signed PDF and send back '{nice} signature.gotoquill' (response code fallback: {CODE_PREFIX}). "
                 f"Then call apply_signature_response(request_id='{rid}', response_path=... or response_text=...)."),
    }, d)


def render_html(page_data: dict, pages_b64: list[str], title: str) -> str:
    tpl = resources.files("gotoquill").joinpath("static/offline.html").read_text(encoding="utf-8")
    blob = json.dumps(page_data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    vendor = Path(__file__).resolve().parent / "web" / "vendor"
    if not vendor.is_dir():
        vendor = Path(__file__).resolve().parent.parent / "web" / "vendor"
    for token, filename in (("__PDF_LIB__", "pdf-lib.min.js"), ("__PDF_JS__", "pdf.min.mjs"),
                            ("__PDF_WORKER__", "pdf.worker.min.mjs")):
        encoded = base64.b64encode((vendor / filename).read_bytes()).decode()
        tpl = tpl.replace(token, encoded)
    licenses = {name: (vendor / name).read_text(encoding="utf-8")
                for name in ("LICENSE.pdf-lib", "LICENSE.pdfjs")}
    tpl = tpl.replace("__PDF_LICENSES__", json.dumps(licenses).replace("<", "\\u003c"))
    return (tpl.replace("__TITLE__", _html.escape(title + " - sign"))
               .replace("/*__DATA__*/null", blob))


# ---------------------------------------------------------------- step 3
def parse_response(response_text: str | None = None, response_path: str | None = None) -> dict:
    if bool(response_text) == bool(response_path):
        raise SignError("provide exactly one of response_path or response_text")
    if response_path:
        p = Path(response_path).expanduser()
        if not p.is_file():
            raise SignError(f"file not found: {response_path}", 404)
        if p.stat().st_size > 8 * 1024 * 1024:
            raise SignError("response file too large", 413)
        response_text = p.read_text(encoding="utf-8", errors="replace")
    t = (response_text or "").strip()
    if len(t) > 8 * 1024 * 1024:
        raise SignError("response too large", 413)
    m = re.search(r"(?:%s|%s)([ZJ])\.([A-Za-z0-9_\-\s]+)" % (re.escape(CODE_PREFIX), re.escape(CODE_PREFIX_LEGACY)), t)
    if m:  # compact code (may have been wrapped / have spaces from a chat app)
        b = re.sub(r"\s+", "", m.group(2))
        try:
            raw = base64.urlsafe_b64decode(b + "=" * (-len(b) % 4))
            if m.group(1) == "Z":
                decoder = zlib.decompressobj(-15)
                raw = decoder.decompress(raw, 8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024 or decoder.unconsumed_tail:
                    raise SignError("expanded signature response too large", 413)
                if not decoder.eof or decoder.unused_data:
                    raise ValueError("invalid compressed response")
            obj = json.loads(raw)
        except (binascii.Error, ValueError, zlib.error) as e:
            raise SignError("the signature code is damaged or incomplete (copy all of it)") from e
    else:
        try:
            obj = json.loads(t[t.index("{"): t.rindex("}") + 1])
        except ValueError as e:
            raise SignError("not a gotoquill signature response") from e
    if not isinstance(obj, dict) or obj.get("type") not in RESPONSE_TYPES:
        raise SignError("not a gotoquill signature response")
    return obj


def apply_signature_response(request_id: str, response_path: str | None = None, response_text: str | None = None,
                             output_path: str | None = None, response_obj: dict | None = None) -> dict:
    if response_obj is not None:
        if not isinstance(response_obj, dict) or response_obj.get("type") not in RESPONSE_TYPES:
            raise SignError("not a gotoquill signature response")
        resp = response_obj
    else:
        resp = parse_response(response_text, response_path)
    with _lock:
        d = _load(request_id)
        if resp.get("request_id") != request_id:
            raise SignError("this signature response is for a different request "
                            f"({resp.get('request_id')!r}), not {request_id}", 409)
        if d["status"] == "completed":
            raise SignError("this request was already signed and applied; a response can be used only once", 409)
        if d["status"] != "pending":
            raise SignError(f"cannot apply: request is {d['status']}", 409)
        now = pdf.utcnow()
        if _parse(d["expires_at"]) < now:
            d["status"] = "expired"
            _store(d)
            raise SignError("this request has expired; create a new one", 410)
        if resp.get("original_sha256") != d["original_sha256"]:
            raise SignError("document hash does not match this request", 409)
        if resp.get("decision") == "decline":
            d.update(status="declined", decline_reason=str(resp.get("decline_reason") or "")[:500] or None,
                     declined_at=_iso(now))
            _store(d)
            return {"request_id": request_id, "status": "declined", "decline_reason": d["decline_reason"]}
        if resp.get("decision") != "sign":
            raise SignError("decision must be 'sign' or 'decline'")
        if resp.get("consent") is not True or resp.get("consent_text") != d["consent_text"]:
            raise SignError("consent is missing or does not match", 400)
        png = _decode_png(str(resp.get("signature_png") or ""), get_settings().max_signature_bytes)
        sig_sha = hashlib.sha256(png).hexdigest()
        method = resp.get("method") if resp.get("method") in ("drawn", "typed") else "drawn"
        typed = str(resp.get("typed_name") or "")[:200]
        name = str(resp.get("signer_name") or "")[:200]
        cts = str(resp.get("client_timestamp") or "")[:40]
        msg = proof_message(request_id, d["original_sha256"], sig_sha, method, typed, name, cts)
        key_b = bytes.fromhex(d["key"])
        good = hmac.new(key_b, msg.encode(), hashlib.sha256).hexdigest()
        # Deprecated agent-sign/v1 proof namespace still accepted for in-flight responses.
        legacy_msg = "|".join(["agent-sign/v1", request_id, d["original_sha256"], sig_sha, method or "", typed or "", name or "", cts or ""])
        good_legacy = hmac.new(key_b, legacy_msg.encode(), hashlib.sha256).hexdigest()
        got = str(resp.get("proof") or "")
        if not (hmac.compare_digest(good, got) or hmac.compare_digest(good_legacy, got)):
            raise SignError("proof check failed: the response was changed or made for another request", 403)
        signed_at = now
        try:
            ct = datetime.fromisoformat(cts.replace("Z", "+00:00"))
            if ct.tzinfo and _parse(d["created_at"]) - timedelta(minutes=5) <= ct <= now + timedelta(minutes=5):
                signed_at = ct.astimezone(timezone.utc)
        except ValueError:
            pass
        original = (_dir(request_id) / "original.pdf").read_bytes()
        signer = name or typed or d["signer_name"] or None
        sctx = signer_context(resp)
        try:
            sctx.update(pdf.validate_date_choice(resp.get("date_format"), resp.get("date_text")))
        except pdf.PdfError as e:
            raise SignError(str(e)) from e
        browser_hash = resp.get("browser_pdf_sha256")
        if browser_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", str(browser_hash)):
            raise SignError("invalid browser PDF hash")
        signed_by = resp.get("signed_by_line") is True
        out_bytes = pdf.stamp(original, d["placements"], png, signed_at, signer, request_id, sctx,
                              signed_by_line=signed_by, plan=d.get("stamp_plan"))
        out = Path(output_path).expanduser().resolve() if output_path else Path(d["output_path"])
        audit_p = default_output_paths(None, str(out), request_id)[1] if output_path else Path(d["audit_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(out_bytes)
        audit = {
            "request_id": request_id, "document_name": d["document_name"], "signer_name": signer,
            "signed_at": _iso(signed_at), "client_timestamp": cts or None, "applied_at": _iso(now),
            "signer_timezone": sctx.get("timezone"), "signer_utc_offset_minutes": sctx.get("utc_offset_minutes"),
            "signer_locale": sctx.get("locale"), "signed_by_line": signed_by,
            "date_format": sctx.get("date_format"), "date_text": sctx.get("date_text"),
            "delivery": d.get("delivery", DELIVERY), "ip": None, "user_agent": str(resp.get("user_agent") or "")[:500],
            "method": method, "typed_name": typed or None, "signature_source": f"newly {method} in " + ("offline file" if d.get("delivery", DELIVERY) == DELIVERY else "sealed-link page"),
            "consent_text": d["consent_text"], "consent_given": True,
            "original_sha256": d["original_sha256"], "signature_sha256": sig_sha,
            "signed_sha256": pdf.sha256(out_bytes),
            "python_pdf_sha256": pdf.sha256(out_bytes), "browser_pdf_sha256": browser_hash,
            "pdf_comparison": "Browser and authoritative Python PDFs are not claimed byte-identical", "proof": "hmac-sha256 verified",
            "response_sha256": hashlib.sha256(json.dumps(resp, sort_keys=True).encode()).hexdigest(),
        }
        audit_p.write_text(json.dumps(audit, indent=2))
        d.update(status="completed", applied_at=audit["applied_at"], output_path=str(out), audit_path=str(audit_p),
                 used_proof=resp["proof"])
        _store(d)
        (_dir(request_id) / "signature.png").write_bytes(png)
    return _finish({"request_id": request_id, "status": "completed", "output_path": str(out),
                    "audit_path": str(audit_p), "audit": audit}, request_id)


def _finish(res: dict, request_id: str) -> dict:
    from . import notify
    from . import placement as _pl
    try:
        d = _load(request_id)
        orig = (_dir(request_id) / "original.pdf").read_bytes()
        res = _pl.finish(res, orig, d.get("placements"), _dir(request_id))
    except (SignError, OSError):
        pass
    notify.maybe_fire(request_id, res)  # completion hooks, exactly once
    return res


def status(request_id: str) -> dict:
    d = _load(request_id)
    if d["status"] == "pending" and _parse(d["expires_at"]) < pdf.utcnow():
        d["status"] = "expired"
        _store(d)
    keep = ("request_id", "status", "delivery", "created_at", "expires_at", "document_name", "html_path",
            "output_path", "audit_path", "decline_reason")
    return _finish({k: d[k] for k in keep if k in d}, request_id)


def cancel(request_id: str) -> dict:
    with _lock:
        d = _load(request_id)
        if d["status"] == "pending":
            d["status"] = "cancelled"
            _store(d)
    return {"request_id": request_id, "status": d["status"]}


def exists(request_id: str) -> bool:
    try:
        return (_dir(request_id) / "state.json").exists()
    except SignError:
        return False
