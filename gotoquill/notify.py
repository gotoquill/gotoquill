"""Getting told when it's signed: completion hooks, a background watcher, and the `gotoquill wait` exit codes.

Agents only act on their own turns, so "call status later" is not enough. This module makes sure something wakes
the agent when the human finishes:
- hooks saved with the request (on_complete_command / on_complete_webhook) fire exactly once on a final status;
- a watcher (detached process for CLI / Python tools, thread or task in the long-lived MCP server) keeps polling the
  relay, stamps the signed PDF and fires the hooks even if the agent forgets to poll.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

FINAL = ("completed", "declined", "expired", "cancelled")
EXIT_CODES = {"completed": 0, "declined": 3, "expired": 4, "cancelled": 5, "timeout": 6}  # 2 = error
_fire_lock = threading.Lock()


def _root() -> Path:
    from .vault import config_dir
    p = config_dir() / "notify"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _rdir(rid: str) -> Path:
    import re
    if not re.fullmatch(r"req_[0-9a-zA-Z_-]{6,64}", rid or ""):
        raise ValueError("bad request_id")
    p = _root() / rid
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_hooks(rid: str, command: str | None = None, webhook: str | None = None,
               webhook_headers: dict | None = None, webhook_body=None, use_saved: bool = True) -> dict | None:
    """Save the request's completion hooks. With no command/webhook, the saved notify targets from
    `gotoquill connect` are used (only their ids are written here; secrets stay in the encrypted store)."""
    from . import targets as T
    from .core import SignError
    h: dict = {}
    try:
        if webhook:
            h["webhook"] = T.check_url(webhook, "on_complete_webhook")
            h["webhook_headers"] = T.check_headers(webhook_headers) or None
            h["webhook_body"] = T.check_body(webhook_body)
        elif webhook_headers or webhook_body:
            raise SignError("webhook_headers / webhook_body need on_complete_webhook")
    except T.TargetError as e:
        raise SignError(str(e)) from e
    if command:
        h["command"] = command
    if not h and use_saved:
        ids = [t["id"] for t in T.targets()]
        if ids:
            h["saved_targets"] = ids
    if not h:
        return None
    h = {"command": h.get("command"), "webhook": h.get("webhook"), **{k: v for k, v in h.items() if k not in ("command", "webhook") and v}}
    p = _rdir(rid) / "hooks.json"
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(h, f)
    return h


def public_hooks(h: dict | None) -> dict | None:
    """What a tool result may show (header literals masked)."""
    if not h:
        return h
    from .targets import mask_value
    out = dict(h)
    if out.get("webhook_headers"):
        out["webhook_headers"] = {k: mask_value(v) for k, v in out["webhook_headers"].items()}
    if out.get("webhook_body") is not None:
        out["webhook_body"] = "(template)"
    return out


def hooks(rid: str) -> dict | None:
    f = _rdir(rid) / "hooks.json"
    return json.loads(f.read_text()) if f.exists() else None


def fired(rid: str) -> bool:
    return (_rdir(rid) / "fired.json").exists()


def maybe_fire(rid: str, st: dict) -> bool:
    """Run the request's hooks once when st is final. Safe to call from many places / processes."""
    if not isinstance(st, dict) or st.get("status") not in FINAL:
        return False
    try:
        h = hooks(rid)
    except ValueError:
        return False
    if not h:
        return False
    marker = _rdir(rid) / "fired.json"
    with _fire_lock:
        try:
            fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)  # atomic across processes
        except FileExistsError:
            return False
        with os.fdopen(fd, "w") as f:
            json.dump({"status": st["status"], "at": time.time()}, f)
    payload = json.dumps(st, default=str).encode()
    log = {}
    if h.get("command"):
        signed_pdf = str(st.get("signed_pdf_path") or (st.get("output_path") if st["status"] == "completed" else "") or "")
        preview = str(st.get("signed_preview_png_path") or "")
        audit = str(st.get("audit_path") or "") if st["status"] == "completed" else ""
        nxt = str(st.get("next") or "")
        hook_env = {
            "GOTOQUILL_REQUEST_ID": rid, "GOTOQUILL_STATUS": st["status"],
            "GOTOQUILL_SIGNED_PDF": signed_pdf, "GOTOQUILL_PREVIEW_PNG": preview,
            "GOTOQUILL_AUDIT": audit, "GOTOQUILL_NEXT": nxt,
            # Deprecated aliases for existing hook scripts:
            "AGENT_SIGN_REQUEST_ID": rid, "AGENT_SIGN_STATUS": st["status"],
            "AGENT_SIGN_SIGNED_PDF": signed_pdf, "AGENT_SIGN_PREVIEW_PNG": preview,
            "AGENT_SIGN_AUDIT": audit, "AGENT_SIGN_NEXT": nxt,
        }
        env = dict(os.environ, **hook_env)
        try:
            p = subprocess.run(h["command"], shell=True, input=payload, env=env, capture_output=True, timeout=120)
            log["command"] = {"exit_code": p.returncode, "stderr": p.stderr.decode(errors="replace")[-2000:]}
        except Exception as e:  # noqa: BLE001
            log["command"] = {"error": str(e)}
    from . import targets as T
    if h.get("webhook"):
        hdrs, missing = T.resolve_headers(h.get("webhook_headers"))
        r = T.post(h["webhook"], T.render_body(h.get("webhook_body"), st, rid), hdrs, rid, st["status"])
        log["webhook"] = {**r, **({"missing_env": missing} if missing else {})}
    if h.get("saved_targets"):
        saved = {t["id"]: t for t in T.targets()}
        log["targets"] = [T.deliver(saved[i], st, rid) if i in saved else {"id": i, "ok": False, "error": "removed"}
                          for i in h["saved_targets"]]
    (_rdir(rid) / "hook-result.json").write_text(json.dumps(log, indent=2))
    return True


def poll_until_final(rid: str, timeout: float | None = None, on_tick=None) -> dict:
    """Block until final (or timeout). Uses the normal status path, so the reply is pulled and the PDF stamped."""
    from .tools import get_signature_status
    end = None if timeout is None else time.monotonic() + max(0.0, timeout)
    while True:
        left = 600.0 if end is None else max(0.0, end - time.monotonic())
        t0 = time.monotonic()
        st = get_signature_status(rid, wait_seconds=min(left, 15.0))
        if st.get("status") in FINAL:
            maybe_fire(rid, st)
            return st
        if on_tick:
            on_tick(st)
        if end is not None and time.monotonic() >= end:
            return st
        spent = time.monotonic() - t0  # file-mode status returns at once: don't spin
        if spent < 2:
            time.sleep(min(2 - spent, 2.0 if end is None else max(0.0, end - time.monotonic())))


def _watch_timeout(rid: str) -> float:
    """Until the request expires (+ a minute), at most 4 hours."""
    try:
        from . import offline
        exp = offline._parse(offline._load(rid)["expires_at"]).timestamp()
        return max(60.0, min(4 * 3600.0, exp - time.time() + 60))
    except Exception:  # noqa: BLE001
        return 4 * 3600.0


def start_watcher(rid: str, mode: str | None = None) -> dict:
    """mode: 'process' (detached; survives this process), 'thread', or 'none'. Env GOTOQUILL_WATCHER overrides."""
    from .envcompat import env_get
    mode = env_get("WATCHER") or mode or "process"
    if mode == "none":
        return {"mode": "none"}
    if mode == "thread":
        t = threading.Thread(target=lambda: poll_until_final(rid, _watch_timeout(rid)), daemon=True,
                             name=f"gotoquill-watch-{rid}")
        t.start()
        return {"mode": "thread"}
    logf = open(_rdir(rid) / "watcher.log", "ab")  # noqa: SIM115
    kw = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x00000008 | 0x00000200}
    p = subprocess.Popen([sys.executable, "-m", "gotoquill", "_watch", rid], stdin=subprocess.DEVNULL,
                         stdout=logf, stderr=logf, close_fds=True, env=dict(os.environ), **kw)
    (_rdir(rid) / "watcher.pid").write_text(str(p.pid))
    return {"mode": "process", "pid": p.pid}


def wait_command(rid: str) -> str:
    return f"gotoquill wait {rid}"


def wake_guidance(rid: str, page: bool = False) -> str:
    status_call = (f"wait_for_signature(request_id='{rid}', wait_seconds=600) (or get_signature_status with "
                   "wait_seconds=600)")
    if page:  # the local page lives in this process: another process cannot watch it
        return ("IMMEDIATELY start waiting; never end your turn assuming you will be told. Call "
                f"{status_call} again and again in this same turn until the status is completed, declined, expired "
                "or cancelled (or pass on_complete_command / on_complete_webhook to request_signature; one-time setup: "
                "`gotoquill connect` / connect_notifications). When "
                "completed, send the signed PDF back to the signer in the chat right away.")
    return ("IMMEDIATELY start waiting in a way that will wake you when the human finishes; never end your turn "
            "assuming you will be told. In priority order: (a) if you can run background shell jobs that notify you "
            f"when they exit, run `{wait_command(rid)}` in the background now (it exits 0 when signed and prints the "
            f"result JSON); (b) otherwise call {status_call} again and again in this same turn until the status is "
            "completed, declined, expired or cancelled; (c) or pass on_complete_command / on_complete_webhook to "
            "request_signature so a watcher runs your command / POSTs to your URL when it is done (one-time setup "
            "instead: `gotoquill connect` / connect_notifications saves targets, e.g. OpenClaw hooks or a webhook, "
            "that are used automatically). When completed, "
            "send the signed PDF back to the signer in the chat right away.")
