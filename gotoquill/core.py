"""Core service: request state, signer actions and stamping. Used by the local signer, MCP server and CLI."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import pdf, vault
from .config import Settings, get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
  id TEXT PRIMARY KEY,
  sign_token_hash TEXT UNIQUE NOT NULL,
  agent_token_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  data TEXT NOT NULL
);
"""
_lock = threading.Lock()


def _sctx(tz, off, loc) -> dict:
    from .offline import signer_context
    c = signer_context({"signer_timezone": tz, "signer_utc_offset": off, "signer_locale": loc})
    return {"signer_timezone": c["timezone"], "signer_utc_offset_minutes": c["utc_offset_minutes"], "signer_locale": c["locale"]}


class SignError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Service:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()
        self.db_path = self.s.data_dir / "gotoquill.sqlite3"
        # one-time "human page" nonces that unlock saved signatures; never given to an agent
        self._vault_nonce: dict[str, str] = {}
        with self._db() as c:
            c.executescript(SCHEMA)

    # ---------- storage ----------
    def _db(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _doc_path(self, rid: str, kind: str) -> Path:
        return self.s.data_dir / "docs" / f"{rid}.{kind}"

    def _load(self, row: sqlite3.Row) -> dict:
        d = json.loads(row["data"])
        d.update(id=row["id"], status=row["status"], created_at=row["created_at"], expires_at=row["expires_at"])
        if d["status"] == "pending" and _parse(d["expires_at"]) < pdf.utcnow():
            d["status"] = "expired"
            self._save(d)
        return d

    def _save(self, d: dict) -> None:
        core = {k: d[k] for k in ("id", "status", "created_at", "expires_at")}
        rest = {k: v for k, v in d.items() if k not in core}
        with self._db() as c:
            c.execute("UPDATE requests SET status=?, data=? WHERE id=?", (core["status"], json.dumps(rest), core["id"]))

    def _by_agent(self, rid: str, agent_token: str) -> dict:
        with self._db() as c:
            row = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
        if not row or not secrets.compare_digest(row["agent_token_hash"], _h(agent_token or "")):
            raise SignError("request not found or bad agent_token", 404)
        return self._load(row)

    def _by_sign_token(self, token: str) -> dict:
        with self._db() as c:
            row = c.execute("SELECT * FROM requests WHERE sign_token_hash=?", (_h(token),)).fetchone()
        if not row:
            raise SignError("link not found", 404)
        return self._load(row)

    # ---------- agent actions ----------
    def request_signature(self, *, pdf_base64: str | None = None, pdf_path: str | None = None,
                          document_name: str | None = None, signer_name: str | None = None,
                          placements: list[dict] | None = None, add_date: bool = False,
                          proof_line: bool = True, date_format: str | None = None,
                          message: str | None = None, expires_in_minutes: int | None = None,
                          delivery: str | None = None, spots=None, return_to: str | None = None) -> dict:
        from .returnto import normalize as _rt
        return_to = _rt(return_to)
        if date_format is not None and date_format not in pdf.DATE_FORMATS:
            raise SignError("date_format must be DD/MM/YYYY, MM/DD/YYYY or YYYY-MM-DD")
        data = self._read_pdf(pdf_base64, pdf_path)
        info = pdf.inspect_pdf(data, self.s.max_pages)
        from . import placement as _pl
        try:
            placements, pinfo = _pl.plan(data, placements, add_date=add_date, spots=spots)
        except ValueError as e:
            raise SignError(str(e)) from e
        if len(placements) > 50:
            raise SignError("too many placements (max 50)")
        # validate placements now so the agent gets errors early
        from .pdfdoc import Document
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
                    pdf.resolve_rect(doc, p)
                except (KeyError, TypeError, ValueError) as e:
                    raise SignError(f"bad placement {p}: {e}") from e
        ttl = expires_in_minutes or self.s.default_ttl_minutes
        if not 1 <= ttl <= self.s.max_ttl_minutes:
            raise SignError(f"expires_in_minutes must be 1..{self.s.max_ttl_minutes}")
        rid = "req_" + secrets.token_hex(8)
        sign_token = secrets.token_urlsafe(32)
        agent_token = secrets.token_urlsafe(32)
        now = pdf.utcnow()
        expires = now + timedelta(minutes=ttl)
        self._doc_path(rid, "pdf").write_bytes(data)
        from .offline import friendly_name
        nice = friendly_name((document_name or (Path(pdf_path).name if pdf_path else "document.pdf"))[:200])
        previews = _pl.preview_pngs(data, placements, self.s.data_dir / "previews" / rid, nice)
        rest = {
            "document_name": (document_name or (Path(pdf_path).name if pdf_path else "document.pdf"))[:200],
            "signer_name": (signer_name or None) and signer_name[:200],
            "message": (message or None) and message[:1000],
            "placements": placements, "page_count": info["page_count"],
            "placement_info": pinfo, "preview_png_paths": previews,
            "original_sha256": pdf.sha256(data), "consent_text": self.s.consent_text,
            "delivery": delivery or "local page on this computer", "return_to": return_to,
        }
        with _lock, self._db() as c:
            c.execute("INSERT INTO requests VALUES (?,?,?,?,?,?,?)",
                      (rid, _h(sign_token), _h(agent_token), "pending", _iso(now), _iso(expires), json.dumps(rest)))
        return {
            "request_id": rid, "agent_token": agent_token, "status": "pending",
            "sign_token": sign_token, "expires_at": _iso(expires), "placements": placements,
            "placement_info": pinfo, "preview_png_paths": previews,
        }

    def get_status(self, rid: str, agent_token: str) -> dict:
        d = self._by_agent(rid, agent_token)
        out = {"request_id": rid, "status": d["status"], "created_at": d["created_at"], "expires_at": d["expires_at"],
               "document_name": d["document_name"]}
        if d["status"] in ("signed", "completed"):
            out["signed_at"] = d["audit"]["signed_at"]
            out["signer_name"] = d["audit"].get("signer_name")
        if d["status"] == "declined":
            out["decline_reason"] = d.get("decline_reason")
        return out

    def apply(self, rid: str, agent_token: str, output_path: str | None = None) -> dict:
        d = self._by_agent(rid, agent_token)
        if d["status"] not in ("signed", "completed"):
            raise SignError(f"cannot apply: status is '{d['status']}'", 409)
        signed_p = self._doc_path(rid, "signed.pdf")
        needs_stamp = not signed_p.exists()
        if needs_stamp:
            original = self._doc_path(rid, "pdf").read_bytes()
            sig = self._doc_path(rid, "sig.png").read_bytes()
            out = pdf.stamp(original, d["placements"], sig, _parse(d["audit"]["signed_at"]),
                            d["audit"].get("signer_name"), rid,
                            {"timezone": d["audit"].get("signer_timezone"), "locale": d["audit"].get("signer_locale"),
                             "utc_offset_minutes": d["audit"].get("signer_utc_offset_minutes"),
                             "date_format": d["audit"].get("date_format"), "date_text": d["audit"].get("date_text")},
                            signed_by_line=bool(d["audit"].get("signed_by_line")))
            signed_p.write_bytes(out)
        if needs_stamp or d["status"] == "signed":
            d["audit"]["signed_sha256"] = pdf.sha256(signed_p.read_bytes())
            d["audit"]["applied_at"] = _iso(pdf.utcnow())
            d["status"] = "completed"
            self._save(d)
            self._doc_path(rid, "audit.json").write_text(json.dumps(d["audit"], indent=2))
        out_bytes = signed_p.read_bytes()
        result = {"request_id": rid, "status": "completed", "audit": d["audit"],
                  "signed_pdf_base64": base64.b64encode(out_bytes).decode()}
        if output_path:
            Path(output_path).write_bytes(out_bytes)
            result["output_path"] = str(Path(output_path).resolve())
        return result

    def cancel(self, rid: str, agent_token: str) -> dict:
        d = self._by_agent(rid, agent_token)
        if d["status"] == "pending":
            d["status"] = "cancelled"
            self._save(d)
        return {"request_id": rid, "status": d["status"]}

    # ---------- signer actions ----------
    def signer_view(self, token: str, vault_once: bool = False) -> dict:
        """Shared links and MCP views never grant access to the owner's vault.

        Vault management remains available through the local CLI/keyring. A
        signing-link nonce is not independent owner authentication.
        """
        d = self._by_sign_token(token)
        saved: dict = {}
        return {**saved, "save_names": [], "status": d["status"], "document_name": d["document_name"], "signer_name": d["signer_name"],
                "message": d["message"], "page_count": d["page_count"], "expires_at": d["expires_at"],
                "consent_text": d["consent_text"], "original_sha256": d["original_sha256"],
                "placements": d["placements"], "boxes": self._boxes(d), "show_footer": self.s.show_footer,
                "return_to": d.get("return_to"), "_id": d["id"]}

    def _boxes(self, d: dict) -> list[dict]:
        from . import placement as _pl
        from .pdfdoc import Document
        try:
            with Document.open(self._doc_path(d["id"], "pdf")) as doc:
                return _pl.boxes(doc, d["placements"])
        except Exception:  # noqa: BLE001
            return []

    def signer_page_png(self, token: str, page: int) -> bytes:
        d = self._by_sign_token(token)
        if d["status"] != "pending":
            raise SignError(f"this link is {d['status']}", 410)
        return pdf.render_page_png(self._doc_path(d["id"], "pdf").read_bytes(), page)

    def _check_nonce(self, token: str, nonce: str | None) -> None:
        raise SignError("saved signatures require local owner access; shared signing views cannot access the vault", 403)

    def delete_saved(self, token: str, vault_nonce: str | None, name: str | None) -> dict:
        self._by_sign_token(token)
        self._check_nonce(token, vault_nonce)
        return {"deleted": vault.delete(name), "saved_signatures": vault.previews()}

    def submit(self, token: str, *, decision: str, signature_png_base64: str | None = None, method: str | None = None,
               typed_name: str | None = None, signer_name: str | None = None, consent: bool = False,
               decline_reason: str | None = None, use_saved: str | None = None, save_as: str | None = None,
               vault_nonce: str | None = None, ip: str | None = None, user_agent: str | None = None,
               signer_timezone: str | None = None, signer_utc_offset: int | None = None,
               signer_locale: str | None = None, signed_by_line: bool = False,
               date_format: str | None = None, date_text: str | None = None, include_pdf: bool = False) -> dict:
        with _lock:
            d = self._by_sign_token(token)
            if d["status"] != "pending":
                raise SignError(f"this link is {d['status']}", 410)
            now = pdf.utcnow()
            if decision == "decline":
                d["status"] = "declined"
                d["decline_reason"] = (decline_reason or "")[:500] or None
                d["audit"] = {"declined_at": _iso(now), "delivery": d.get("delivery"), "ip": ip, "user_agent": (user_agent or "")[:500]}
                self._save(d)
                return {"status": "declined"}
            if decision != "sign":
                raise SignError("decision must be 'sign' or 'decline'")
            if not consent:
                raise SignError("consent is required to sign")
            try:
                date_choice = pdf.validate_date_choice(date_format, date_text)
            except pdf.PdfError as e:
                raise SignError(str(e)) from e
            if use_saved:
                self._check_nonce(token, vault_nonce)
                try:
                    png = vault.get_png(use_saved)
                    png = _decode_png(base64.b64encode(png).decode(), self.s.max_signature_bytes)
                except vault.VaultError as e:
                    raise SignError(str(e), 404) from e
                source = "saved signature reused"
            else:
                png = _decode_png(signature_png_base64 or "", self.s.max_signature_bytes)
                method = method if method in ("drawn", "typed") else "drawn"
                source = f"newly {method}"
            saved_meta = None
            if save_as and not use_saved:
                self._check_nonce(token, vault_nonce)
                try:
                    saved_meta = vault.save(save_as, png, method, (signer_name or typed_name or "").strip()[:200] or None)
                except vault.VaultError as e:
                    raise SignError(f"could not save signature: {e}") from e
            name = (signer_name or typed_name or d["signer_name"] or "").strip()[:200] or None
            self._doc_path(d["id"], "sig.png").write_bytes(png)
            d["status"] = "signed"
            d["audit"] = {
                "request_id": d["id"], "document_name": d["document_name"], "signer_name": name,
                **_sctx(signer_timezone, signer_utc_offset, signer_locale), **date_choice,
                "signed_at": _iso(now), "delivery": d.get("delivery"), "ip": ip, "user_agent": (user_agent or "")[:500],
                "method": "saved" if use_saved else method,
                "signature_source": source, "saved_signature_reused": bool(use_saved),
                "saved_signature_name": use_saved or None,
                "saved_for_next_time": bool(saved_meta),
                "consent_text": d["consent_text"], "consent_given": True, "signed_by_line": bool(signed_by_line),
                "original_sha256": d["original_sha256"], "signature_sha256": pdf.sha256(png),
                "signed_sha256": None,
            }
            result = {"status": "signed"}
            if include_pdf:
                # Return the PDF in this response before the one-request server closes.
                out = pdf.stamp(self._doc_path(d["id"], "pdf").read_bytes(), d["placements"], png, now, name, d["id"],
                                {"timezone": signer_timezone, "utc_offset_minutes": signer_utc_offset,
                                 "locale": signer_locale, **date_choice}, signed_by_line=bool(signed_by_line))
                self._doc_path(d["id"], "signed.pdf").write_bytes(out)
                result["signed_pdf_base64"] = base64.b64encode(out).decode()
            self._save(d)
            self._vault_nonce.pop(token, None)
            return result

    # ---------- helpers ----------
    def _read_pdf(self, b64: str | None, path: str | None) -> bytes:
        if bool(b64) == bool(path):
            raise SignError("provide exactly one of pdf_path or pdf_base64")
        if path:
            p = Path(path).expanduser()
            if not p.is_file():
                raise SignError(f"file not found: {path}", 404)
            if p.stat().st_size > self.s.max_pdf_bytes:
                raise SignError("PDF too large", 413)
            data = p.read_bytes()
        else:
            if len(b64) > self.s.max_pdf_bytes * 4 // 3 + 16:
                raise SignError("PDF too large", 413)
            try:
                data = base64.b64decode(b64.split(",", 1)[-1] if b64.startswith("data:") else b64, validate=True)
            except (binascii.Error, ValueError) as e:
                raise SignError("pdf_base64 is not valid base64") from e
        if len(data) > self.s.max_pdf_bytes:
            raise SignError("PDF too large", 413)
        try:
            pdf.inspect_pdf(data, self.s.max_pages)
        except pdf.PdfError as e:
            raise SignError(str(e)) from e
        return data


def _decode_png(b64: str, limit: int) -> bytes:
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[-1]
    if not b64 or len(b64) > limit * 4 // 3 + 16:
        raise SignError("signature image missing or too large")
    try:
        png = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise SignError("signature is not valid base64") from e
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SignError("signature must be a PNG image")
    if len(png) > limit:
        raise SignError("signature image too large")
    from PIL import Image, ImageChops, UnidentifiedImageError
    import io
    try:
        with Image.open(io.BytesIO(png)) as image:
            if image.format != "PNG" or not 0 < image.width * image.height <= 16_000_000:
                raise ValueError("invalid dimensions")
            image.verify()
        with Image.open(io.BytesIO(png)) as image:
            rgba = image.convert("RGBA")
            # Composite on white so transparent RGB values cannot count as ink.
            visible = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("RGB")
            if ImageChops.difference(visible, Image.new("RGB", visible.size, "white")).getbbox() is None:
                raise ValueError("blank image")
    except (ValueError, OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError) as e:
        raise SignError("signature must be a valid PNG with visible ink") from e
    return png


_service: Service | None = None


def get_service() -> Service:
    global _service
    if _service is None:
        _service = Service()
    return _service


def reset_service(settings: Settings | None = None) -> Service:
    global _service
    _service = Service(settings)
    return _service


