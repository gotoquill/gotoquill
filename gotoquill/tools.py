"""Plain-Python tool API for non-MCP agents (OpenAI / Gemini / LangChain function calling).

    from gotoquill.tools import FUNCTIONS, call
    tools = FUNCTIONS                       # OpenAI-style function schemas (schemas/functions.json)
    result = call("request_signature", {"pdf_path": "contract.pdf"})
"""
from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from .core import SignError
from .local import get_signer


def _load_functions() -> list[dict]:
    try:  # installed wheel
        return json.loads(resources.files("gotoquill").joinpath("functions.json").read_text())
    except (FileNotFoundError, OSError):  # source checkout
        return json.loads((Path(__file__).resolve().parents[1] / "schemas" / "functions.json").read_text())


FUNCTIONS: list[dict] = _load_functions()


def _create(pdf_path: str, delivery: str = "link", html_path: str | None = None, **kw: Any) -> dict:
    if delivery in ("link", "sealed", "link-file") and not kw.get("share_link"):
        from . import sealed
        kw.pop("open_browser", None); kw.pop("share_link", None)
        as_file = bool(kw.pop("as_file", False)) or delivery == "link-file"
        return sealed.create_sealed_request(pdf_path=pdf_path, as_file=as_file,
                                            html_path=html_path if as_file else None, **kw)
    if delivery == "file":
        from . import offline
        kw.pop("open_browser", None); kw.pop("share_link", None)
        return offline.create_file_request(pdf_path=pdf_path, html_path=html_path, **kw)
    if delivery not in ("page", "link", "sealed"):
        raise SignError("delivery must be 'link', 'link-file', 'page' or 'file'")
    return get_signer().request(pdf_path=pdf_path, **kw)


def attach_hooks(r: dict, on_complete_command: str | None, on_complete_webhook: str | None,
                 watcher: str | None = None, webhook_headers: dict | None = None, webhook_body=None) -> dict:
    """Save completion hooks for request r and start a watcher that fires them even if the agent never polls.
    watcher: 'process' (detached, default for link modes), 'thread' (in this process; page mode), 'none'."""
    from . import notify
    rid = r["request_id"]
    h = notify.save_hooks(rid, on_complete_command, on_complete_webhook, webhook_headers, webhook_body)
    if not h:
        return r
    r["hooks"] = notify.public_hooks(h)
    if h.get("saved_targets"):
        r["notify_targets"] = h["saved_targets"]
        if r.get("next"):
            r["next"] += (" Saved notify targets (" + ", ".join(h["saved_targets"]) + ") will also be told when it "
                          "finishes; still wait in this turn as above if you can.")
    if rid in get_signer().sessions:
        w = notify.start_watcher(rid, "thread")  # the local page lives in this process
    elif rid_sealed(rid):
        w = notify.start_watcher(rid, watcher or "process")
    else:  # delivery='file': hooks fire when apply_signature_response is called
        w = {"mode": "on apply_signature_response"}
    r["watcher"] = w
    return r


def request_signature(pdf_path: str, delivery: str = "link", html_path: str | None = None,
                      on_complete_command: str | None = None, on_complete_webhook: str | None = None,
                      return_to: str | None = None, wait_seconds: float = 0,
                      webhook_headers: dict | None = None, webhook_body: Any = None, **kw: Any) -> dict:
    """wait_seconds > 0: block (max 600) after creating the request; the result then has final_status."""
    from .returnto import normalize
    watcher = kw.pop("watcher", None)
    r = _create(pdf_path, delivery, html_path, return_to=normalize(return_to), **kw)
    r = attach_hooks(r, on_complete_command, on_complete_webhook, watcher, webhook_headers, webhook_body)
    r["wait_tool"] = f"wait_for_signature(request_id='{r['request_id']}', wait_seconds=600)"
    if wait_seconds and float(wait_seconds) > 0 and delivery != "file":
        st = wait_for_signature(r["request_id"], wait_seconds)
        r.update(final_status=st, status=st.get("status", r.get("status")))
        if st.get("next"):
            r["next"] = st["next"]
    return r


def connect_notifications(action: str = "connect", webhook_url: str | None = None, headers: dict | None = None,
                          body_template: Any = None, name: str | None = None,
                          telegram_bot_token_env: str | None = None, chat_id: str | None = None,
                          openclaw: bool | None = None, openclaw_config: str | None = None,
                          openclaw_url: str | None = None, openclaw_action: str = "wake",
                          openclaw_agent: str | None = None, yes: bool = False, test: bool = True,
                          target_id: str | None = None) -> dict:
    """One-time setup (action='connect'), or 'status' / 'test' / 'remove'. Secrets are never returned."""
    from . import connect as C
    from . import targets as T
    try:
        if action == "status":
            return T.status()
        if action == "remove":
            return {"removed": T.remove(target_id)}
        if action == "test":
            return C.run_tests()
        if action != "connect":
            return {"error": "action must be connect, status, test or remove", "code": 400}
        return C.connect(webhook=webhook_url, headers=T.check_headers(headers), body=body_template, name=name,
                         telegram_bot_token_env=telegram_bot_token_env, chat_id=chat_id, openclaw=openclaw,
                         openclaw_config=openclaw_config, openclaw_url_=openclaw_url, openclaw_action=openclaw_action,
                         openclaw_agent=openclaw_agent, yes=yes, test=test)
    except T.TargetError as e:
        return {"error": str(e), "code": 400}


def wait_for_signature(request_id: str, wait_seconds: float = 600) -> dict:
    """Block up to wait_seconds (max 600) until the request is final; same result as get_signature_status."""
    from . import notify
    wait = max(0.0, min(float(wait_seconds or 0), 600))
    st = notify.poll_until_final(request_id, wait)
    if st.get("status") == "pending":
        st["next"] = (f"Still pending. Call wait_for_signature(request_id='{request_id}', wait_seconds=600) again "
                      "now, in this same turn, until it is completed/declined/expired/cancelled. Do not end your turn "
                      "assuming you will be told.")
    return st


def _offline(rid: str) -> bool:
    from . import offline
    return rid not in get_signer().sessions and offline.exists(rid)


def rid_sealed(rid: str) -> bool:
    from . import sealed
    return rid not in get_signer().sessions and sealed.is_sealed(rid)


def get_signature_status(request_id: str, wait_seconds: float = 0) -> dict:
    from . import sealed
    if rid_sealed(request_id):
        return sealed.status(request_id, wait_seconds)
    if _offline(request_id):
        from . import offline
        return offline.status(request_id)
    return get_signer().status(request_id, wait_seconds)


def cancel_request(request_id: str) -> dict:
    if _offline(request_id):
        from . import offline
        return offline.cancel(request_id)
    return get_signer().cancel(request_id)


def apply_signature_response(request_id: str, response_path: str | None = None, response_text: str | None = None,
                             output_path: str | None = None) -> dict:
    from . import offline
    return offline.apply_signature_response(request_id, response_path=response_path, response_text=response_text,
                                            output_path=output_path)


def sign_pdf(pdf_path: str, timeout: float | None = None, **kw: Any) -> dict:
    """Blocking helper: open the signing page and wait until the human signs, declines or it expires."""
    s = get_signer()
    r = s.request(pdf_path=pdf_path, **kw)
    return s.wait(r["request_id"], timeout)


_DISPATCH = {"request_signature": request_signature, "get_signature_status": get_signature_status,
             "wait_for_signature": wait_for_signature, "connect_notifications": connect_notifications,
             "cancel_request": cancel_request, "apply_signature_response": apply_signature_response}


def call(name: str, arguments: dict | str | None = None) -> dict:
    """Run a tool by name with JSON arguments; errors come back as {"error": ...}."""
    args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
    if name not in _DISPATCH:
        return {"error": f"unknown tool {name}"}
    try:
        return _DISPATCH[name](**args)
    except SignError as e:
        return {"error": str(e), "code": e.code}
    except TypeError as e:
        return {"error": f"bad arguments: {e}"}
