"""Local signing sessions: a temporary page on 127.0.0.1 (random free port) per request.

Flow: request() -> page starts, browser opens -> human signs -> signed PDF + audit JSON are written
next to the original (or to output_path) -> the page shuts down.
"""
from __future__ import annotations

import base64
import json
import socket
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core import SignError, get_service

FINAL = {"completed", "declined", "expired", "cancelled"}


def default_output_paths(pdf_path: str | None, output_path: str | None, rid: str) -> tuple[Path, Path]:
    if output_path:
        out = Path(output_path).expanduser().resolve()
    elif pdf_path:
        from .offline import friendly_name
        src = Path(pdf_path).expanduser().resolve()
        out = src.with_name(f"{src.stem.replace('_', ' ').strip() or 'document'} - signed.pdf")
    else:
        out = (get_service().s.data_dir / "signed" / f"Signed document {rid.replace('req_', '')}.pdf").resolve()
    audit = out.with_name(out.name[:-4] + ".audit.json" if out.name.lower().endswith(".pdf") else out.name + ".audit.json")
    return out, audit


class _Server:
    """uvicorn on a pre-bound 127.0.0.1 socket, in a daemon thread."""

    def __init__(self, app):
        import uvicorn
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.host, self.port = self.sock.getsockname()[:2]
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, lifespan="off"))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]}, daemon=True,
                                       name=f"gotoquill-{self.port}")

    def start(self, timeout: float = 10) -> None:
        self.thread.start()
        t0 = time.monotonic()
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() - t0 > timeout:
                raise SignError("could not start the local signing page", 500)
            time.sleep(0.02)

    def stop(self) -> None:
        self.server.should_exit = True
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=5)
        try:
            self.sock.close()
        except OSError:
            pass

    @property
    def running(self) -> bool:
        return self.thread.is_alive()


@dataclass
class Session:
    request_id: str
    agent_token: str
    sign_token: str
    output_path: Path
    audit_path: Path
    expires_at: str
    server: _Server | None = None
    sign_url: str | None = None
    local_url: str | None = None
    share_link: bool = False
    tunnel: Any = None
    status: str = "pending"
    result: dict = field(default_factory=dict)
    finalized: bool = False
    done: threading.Event = field(default_factory=threading.Event)
    timer: threading.Timer | None = None


class LocalSigner:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self._by_token: dict[str, str] = {}
        self._lock = threading.RLock()

    # ---------- public API ----------
    def request(self, *, pdf_path: str | None = None, pdf_base64: str | None = None, output_path: str | None = None,
                signer_name: str | None = None, document_name: str | None = None, placements: list[dict] | None = None,
                add_date: bool = False, message: str | None = None, expires_in_minutes: int | None = None,
                proof_line: bool = True, date_format: str | None = None, open_browser: bool | None = None, serve: bool = True, share_link: bool | None = None,
                spots=None, return_to: str | None = None) -> dict:
        svc = get_service()
        share = svc.s.share_link if share_link is None else bool(share_link)
        if share and not serve:
            raise SignError("share_link needs the signing page (serve=True)")
        if share and expires_in_minutes is None:
            expires_in_minutes = svc.s.share_ttl_minutes
        r = svc.request_signature(pdf_base64=pdf_base64, pdf_path=pdf_path, document_name=document_name,
                                  signer_name=signer_name, placements=placements, add_date=add_date,
                                  proof_line=proof_line, date_format=date_format,
                                  message=message, expires_in_minutes=expires_in_minutes,
                                  delivery="share link via tunnel" if share else None, spots=spots,
                                  return_to=return_to)
        rid = r["request_id"]
        out, audit = default_output_paths(pdf_path, output_path, rid)
        s = Session(rid, r["agent_token"], r["sign_token"], out, audit, r["expires_at"], share_link=share)
        with self._lock:
            self.sessions[rid] = s
            self._by_token[s.sign_token] = rid
        if serve:
            from .api import AttemptGuard, create_app
            hosts: set[str] = set()
            guard = AttemptGuard(s.sign_token, svc.s.share_max_bad_attempts, svc.s.share_max_submits) if share else None
            s.server = _Server(create_app(on_submit=self._on_submit, extra_hosts=hosts, attempts=guard))
            s.server.start()
            s.local_url = s.sign_url = f"http://127.0.0.1:{s.server.port}/s/{s.sign_token}"
            if share:
                from . import tunnel
                t = tunnel.tunnel_factory(s.server.port)
                try:
                    base = t.start()
                except Exception as e:
                    s.server.stop()
                    svc.cancel(rid, s.agent_token)
                    s.status, s.finalized = "cancelled", True
                    s.done.set()
                    raise e if isinstance(e, SignError) else SignError(f"phone link failed: {e}", 502) from e
                s.tunnel = t
                hosts.add(t.hostname)  # only this exact tunnel hostname, only for this request
                s.sign_url = f"{base}/s/{s.sign_token}"
                if hasattr(t, "wait_ready"):
                    t.wait_ready()
        ttl = (expires_in_minutes or svc.s.default_ttl_minutes) * 60
        s.timer = threading.Timer(ttl + 1, self._expire, args=(rid,))
        s.timer.daemon = True
        s.timer.start()
        opened = False
        if share and open_browser is None:
            open_browser = False  # the human is on another device; the agent sends them the link
        if s.sign_url and (svc.s.open_browser if open_browser is None else open_browser):
            try:
                opened = webbrowser.open(s.sign_url, new=2)
            except Exception:  # noqa: BLE001
                opened = False
        from . import notify as _notify
        from .offline import preview_fields
        pf = preview_fields(r)
        tip = pf.pop("_preview_tip")
        return {
            "request_id": rid, "status": "pending", "sign_url": s.sign_url, "local_url": s.local_url,
            "share_link": share, "browser_opened": opened,
            "expires_at": s.expires_at, "output_path": str(out), "audit_path": str(audit), **pf,
            "next": tip + "Then send the user the sign_url. Then " + _notify.wake_guidance(rid, page=True),
        }

    def status(self, request_id: str, wait_seconds: float = 0) -> dict:
        s = self._get(request_id)
        if wait_seconds and not s.done.is_set():
            s.done.wait(min(float(wait_seconds), 600))
        self._refresh(s)
        return self._public(s)

    def wait(self, request_id: str, timeout: float | None = None) -> dict:
        s = self._get(request_id)
        end = None if timeout is None else time.monotonic() + timeout
        while not s.done.wait(1.0):
            self._refresh(s)
            if end is not None and time.monotonic() > end:
                break
        return self._public(s)

    def cancel(self, request_id: str) -> dict:
        s = self._get(request_id)
        get_service().cancel(s.request_id, s.agent_token)
        self._refresh(s)
        return self._public(s)

    def shutdown(self) -> None:
        for s in list(self.sessions.values()):
            self._close(s)

    # ---------- signer actions without HTTP (used by the MCP Apps in-chat view) ----------
    def ui_view(self, sign_token: str, width_px: int = 800) -> dict:
        svc = get_service()
        v = svc.signer_view(sign_token, vault_once=True)
        v.pop("_id", None)
        pages = []
        if v["status"] == "pending":
            from . import pdf
            data = svc._doc_path(self._rid_for(sign_token), "pdf").read_bytes()
            for p in range(1, min(v["page_count"], 50) + 1):
                png = pdf.render_page_png(data, p, width_px)
                pages.append("data:image/png;base64," + base64.b64encode(png).decode())
        return {**v, "pages": pages}

    def ui_delete_saved(self, sign_token: str, vault_nonce: str | None, name: str | None = None) -> dict:
        return get_service().delete_saved(sign_token, vault_nonce, name)

    def ui_submit(self, sign_token: str, **body: Any) -> dict:
        r = get_service().submit(sign_token, **body, ip="mcp-app", user_agent="MCP Apps in-chat view")
        self._on_submit(sign_token, r["status"])
        try:
            r = {**r, "request_id": self._rid_for(sign_token)}
        except Exception:  # noqa: BLE001
            pass
        return r

    # ---------- internals ----------
    def _rid_for(self, sign_token: str) -> str:
        rid = self._by_token.get(sign_token)
        if not rid:
            raise SignError("link not found", 404)
        return rid

    def _get(self, rid: str) -> Session:
        s = self.sessions.get(rid)
        if not s:
            raise SignError("unknown request_id", 404)
        return s

    def _on_submit(self, sign_token: str, status: str) -> None:
        rid = self._by_token.get(sign_token)
        if rid:
            # finish off-thread so the page gets its response before the server stops
            threading.Thread(target=self._refresh, args=(self.sessions[rid], 0.5), daemon=True).start()

    def _expire(self, rid: str) -> None:
        s = self.sessions.get(rid)
        if s:
            self._refresh(s)

    def _refresh(self, s: Session, delay: float = 0) -> None:
        with self._lock:
            if s.finalized:
                return
            st = get_service().get_status(s.request_id, s.agent_token)
            s.status = st["status"]
            if s.status == "signed":
                r = get_service().apply(s.request_id, s.agent_token, str(s.output_path))
                s.audit_path.write_text(json.dumps(r["audit"], indent=2))
                s.status = "completed"
                s.result = {"audit": r["audit"], "signer_name": r["audit"].get("signer_name"),
                            "signed_at": r["audit"]["signed_at"]}
            elif s.status == "declined":
                s.result = {"decline_reason": st.get("decline_reason")}
            if s.status not in FINAL:
                return
            s.finalized = True
        if delay:
            time.sleep(delay)
        self._close(s)
        s.done.set()

    def _close(self, s: Session) -> None:
        if s.timer:
            s.timer.cancel()
        if s.tunnel:
            try:
                s.tunnel.stop()
            except Exception:  # noqa: BLE001
                pass
        if s.server:
            s.server.stop()

    def _public(self, s: Session) -> dict:
        out = {"request_id": s.request_id, "status": s.status, "sign_url": s.sign_url, "expires_at": s.expires_at,
               "page_running": bool(s.server and s.server.running),
               "local_url": s.local_url, "share_link": s.share_link}
        if s.share_link:
            out["tunnel_running"] = bool(s.tunnel and getattr(s.tunnel, "running", False))
        if s.status == "completed":
            out.update(output_path=str(s.output_path), audit_path=str(s.audit_path), **s.result)
            from . import placement as _pl
            svc = get_service()
            try:
                d = svc._by_agent(s.request_id, s.agent_token)
                orig = svc._doc_path(s.request_id, "pdf").read_bytes()
                _pl.finish(out, orig, d["placements"], svc.s.data_dir / "previews" / s.request_id)
            except (SignError, OSError):
                pass
        elif s.status == "pending":
            out.update(output_path=str(s.output_path), audit_path=str(s.audit_path))
        else:
            out.update(s.result)
        from . import notify
        notify.maybe_fire(s.request_id, out)
        return out


_signer: LocalSigner | None = None


def get_signer() -> LocalSigner:
    global _signer
    if _signer is None:
        _signer = LocalSigner()
    return _signer


def reset_signer() -> LocalSigner:
    global _signer
    if _signer:
        _signer.shutdown()
    _signer = LocalSigner()
    return _signer
