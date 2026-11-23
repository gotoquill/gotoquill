"""`gotoquill connect`: one-time setup so a finished signature wakes the agent with no copy/paste.

It saves "notify targets" (see targets.py) that request_signature uses automatically, and, where a host allows
it, registers gotoquill in that host's own documented config:

* OpenClaw: inbound Gateway hooks in openclaw.json ($OPENCLAW_CONFIG_PATH, else $OPENCLAW_STATE_DIR/openclaw.json,
  else ~/.openclaw/openclaw.json). It sets hooks.enabled, a hooks.token (kept if one exists) and adds a mapping
  `gotoquill` (POST <gateway>/hooks/gotoquill). Default action "wake": a system event for the agent's main session,
  so the conversation the human is in continues. action="agent": an agent run in the persistent session
  "hook:gotoquill" that announces to the last channel.
* Any webhook (n8n, Zapier, Make, LangGraph, your server): URL + headers (literal or env:VAR).
* Telegram: Bot API sendMessage to a chat (bot token read from an env var at send time).

Rules: an existing host config is only changed with yes=True (otherwise a masked diff/plan is returned); the original
is backed up first; secrets are never returned or printed.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import secrets
import shutil
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import targets as T

OPENCLAW_MAPPING_ID = "gotoquill"
OPENCLAW_SESSION_KEY = "hook:gotoquill"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ------------------------------------------------------------------ OpenClaw
def openclaw_config_path() -> Path:
    if os.environ.get("OPENCLAW_CONFIG_PATH", "").strip():
        return Path(os.environ["OPENCLAW_CONFIG_PATH"].strip()).expanduser()
    return openclaw_state_dir() / "openclaw.json"


def openclaw_state_dir() -> Path:
    if os.environ.get("OPENCLAW_STATE_DIR", "").strip():
        return Path(os.environ["OPENCLAW_STATE_DIR"].strip()).expanduser()
    home = os.environ.get("OPENCLAW_HOME", "").strip() or os.path.expanduser("~")
    return Path(home) / ".openclaw"


def openclaw_detected() -> bool:
    return openclaw_config_path().exists() or openclaw_state_dir().is_dir() or bool(shutil.which("openclaw"))


def _masked(cfg: dict) -> str:
    c = json.loads(json.dumps(cfg))
    if isinstance(c.get("hooks"), dict) and c["hooks"].get("token"):
        c["hooks"]["token"] = "***"
    return json.dumps(c, indent=2, ensure_ascii=False) + "\n"


def openclaw_plan(cfg: dict, action: str = "wake", agent_id: str | None = None) -> tuple[dict, str, list[str]]:
    """Return (new config, hook token, notes). Pure function: does not write anything."""
    new = json.loads(json.dumps(cfg))
    hooks = new.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise T.TargetError("openclaw.json: 'hooks' is not an object")
    notes: list[str] = []
    tok = hooks.get("token")
    if not isinstance(tok, str) or not tok or tok.startswith("${"):
        if tok:
            notes.append("hooks.token is an env reference; gotoquill needs the value, so it sets its own token")
        tok = secrets.token_urlsafe(32)
        hooks["token"] = tok
    hooks["enabled"] = True
    hooks.setdefault("path", "/hooks")
    m: dict[str, Any] = {"id": OPENCLAW_MAPPING_ID, "match": {"path": "gotoquill", "source": "gotoquill"},
                         "action": action, "name": "gotoquill", "wakeMode": "now"}
    if action == "wake":
        m["textTemplate"] = "{{message}}"
    else:
        m.update(sessionKey=OPENCLAW_SESSION_KEY, sessionMode="persistent", messageTemplate="{{message}}",
                 deliver=True, channel="last")
        pre = hooks.get("allowedSessionKeyPrefixes")
        if isinstance(pre, list) and [p for p in pre if str(p).strip()] and \
                not any(OPENCLAW_SESSION_KEY.lower().startswith(str(p).lower()) for p in pre if str(p).strip()):
            hooks["allowedSessionKeyPrefixes"] = pre + [OPENCLAW_SESSION_KEY]
    if agent_id:
        m["agentId"] = agent_id
        allowed = hooks.get("allowedAgentIds")
        if isinstance(allowed, list) and agent_id not in allowed and "*" not in allowed:
            notes.append(f"hooks.allowedAgentIds does not include '{agent_id}'; add it or the hook is rejected")
    maps = hooks.get("mappings") if isinstance(hooks.get("mappings"), list) else []
    maps = [x for x in maps if not (isinstance(x, dict) and x.get("id") == OPENCLAW_MAPPING_ID)]
    hooks["mappings"] = [m] + maps  # first match wins; ours only matches path gotoquill + source gotoquill
    return new, tok, notes


def openclaw_url(cfg: dict) -> str:
    port = os.environ.get("OPENCLAW_GATEWAY_PORT", "").strip()
    port = int(port) if port.isdigit() else (cfg.get("gateway", {}) or {}).get("port") or 18789
    path = "/" + str((cfg.get("hooks") or {}).get("path") or "/hooks").strip("/")
    return f"http://127.0.0.1:{int(port)}{path}/gotoquill"


def setup_openclaw(yes: bool = False, config_path: str | None = None, url: str | None = None,
                   action: str = "wake", agent_id: str | None = None) -> dict:
    if action not in ("wake", "agent"):
        raise T.TargetError("openclaw action must be 'wake' or 'agent'")
    p = Path(config_path).expanduser() if config_path else openclaw_config_path()
    out: dict[str, Any] = {"host": "openclaw", "config_path": str(p)}
    exists = p.exists()
    if exists and p.is_symlink():
        raise T.TargetError(f"{p} is a symlink; OpenClaw replaces symlinked configs. Point OPENCLAW_CONFIG_PATH at the real file")
    old_text = p.read_text(encoding="utf-8") if exists else ""
    try:
        cfg = json.loads(old_text) if old_text.strip() else {}
    except ValueError:
        # JSON5 (comments, trailing commas, unquoted keys): rewriting would drop the user's comments. Don't touch it.
        new, _, notes = openclaw_plan({}, action, agent_id)
        return {**out, "ok": False, "changed": False, "error": "openclaw.json is JSON5 (comments etc.); not editing it",
                "manual": "Merge this into your openclaw.json (pick your own long random token), then run "
                          "`gotoquill connect --openclaw --yes` again after it is plain JSON, or add the target with "
                          "--webhook <gateway>/hooks/gotoquill --header-env Authorization=VAR:\n" + _masked(new)}
    if not isinstance(cfg, dict):
        raise T.TargetError("openclaw.json is not a JSON object")
    new, tok, notes = openclaw_plan(cfg, action, agent_id)
    old_m, new_m = (_masked(cfg) if exists else ""), _masked(new)
    changed = json.dumps(cfg, sort_keys=True) != json.dumps(new, sort_keys=True)
    out["plan"] = "".join(difflib.unified_diff(old_m.splitlines(True), new_m.splitlines(True),
                                               str(p) + (" (current)" if exists else " (new)"), str(p) + " (proposed)"))
    out["notes"] = notes
    if changed and exists and not yes:
        return {**out, "ok": False, "changed": False, "needs_confirmation": True,
                "next": "Review the plan (token masked). Re-run with --yes (MCP: yes=true) to apply; a backup is made."}
    if changed:
        if exists:
            bak = p.with_name(p.name + ".gotoquill-backup-" + time.strftime("%Y%m%d-%H%M%S"))
            shutil.copy2(p, bak)
            os.chmod(bak, 0o600)
            out["backup"] = str(bak)
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = stat.S_IMODE(p.stat().st_mode) if exists else 0o600
        tmp = p.with_name(p.name + "." + secrets.token_hex(4) + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
        os.chmod(tmp, mode & 0o600 or 0o600)
        os.replace(tmp, p)  # atomic, like OpenClaw's own writes
    t = T.add({"id": "openclaw", "kind": "openclaw", "url": url or openclaw_url(new), "token": tok,
               "config_path": str(p), "action": action, "added_at": _now()})
    return {**out, "ok": True, "changed": changed, "target": T.public(t)}


# ------------------------------------------------------------------ entry point
def parse_headers(pairs: list[str] | None, env_pairs: list[str] | None) -> dict:
    h: dict[str, str] = {}
    for kv in pairs or []:
        k, sep, v = kv.partition("=")
        if not sep:
            raise T.TargetError(f"--header needs K=V, got {kv!r}")
        h[k.strip()] = v.strip()
    for kv in env_pairs or []:
        k, sep, v = kv.partition("=")
        if not sep:
            raise T.TargetError(f"--header-env needs K=ENVVAR, got {kv!r}")
        h[k.strip()] = "env:" + v.strip()
    return h


def test_ping(t: dict, retries: int = 1) -> dict:
    st = {"status": "test", "event": "test", "document_name": "gotoquill test"}
    r: dict = {}
    for i in range(max(1, retries)):
        r = T.deliver(t, st, "req_testping")
        if r.get("ok"):
            break
        time.sleep(1.5)  # e.g. the OpenClaw Gateway hot-reloading hooks
    return r


def connect(webhook: str | None = None, headers: dict | None = None, body: Any = None, name: str | None = None,
            telegram_bot_token_env: str | None = None, chat_id: str | None = None,
            openclaw: bool | None = None, openclaw_config: str | None = None, openclaw_url_: str | None = None,
            openclaw_action: str = "wake", openclaw_agent: str | None = None,
            yes: bool = False, test: bool = True) -> dict:
    """Set up notify targets. openclaw=None: auto-detect; True: force; False: skip."""
    res: dict[str, Any] = {"ok": True, "configured": [], "tests": [], "notes": []}
    T.secret(create=True)  # local HMAC secret for X-Gotoquill-Signature
    new_targets: list[dict] = []
    if webhook:
        new_targets.append(T.add({"id": name or "webhook", "kind": "webhook", "url": webhook, "headers": headers or {},
                                  "body": body, "added_at": _now()}))
    elif headers or body:
        raise T.TargetError("--header / --header-env / --body-template need --webhook")
    if telegram_bot_token_env or chat_id:
        new_targets.append(T.add({"id": name if (name and not webhook) else "telegram", "kind": "telegram",
                                  "bot_token_env": telegram_bot_token_env, "chat_id": str(chat_id or ""),
                                  "added_at": _now()}))
        if not os.environ.get(telegram_bot_token_env or ""):
            res["notes"].append(f"{telegram_bot_token_env} is not set in this environment; set it where gotoquill "
                                "runs (the token is read at send time and never stored)")
    oc = openclaw if openclaw is not None else (openclaw_detected() and not (webhook or telegram_bot_token_env))
    if oc:
        r = setup_openclaw(yes=yes, config_path=openclaw_config, url=openclaw_url_, action=openclaw_action,
                           agent_id=openclaw_agent)
        res["openclaw"] = {k: v for k, v in r.items() if k != "target"}
        if r.get("ok"):
            new_targets.append(next(t for t in T.targets() if t["id"] == "openclaw"))
        else:
            res["ok"] = False
    if not new_targets and not oc:
        res["ok"] = False
        res["error"] = ("No supported host detected and nothing given. Use --webhook URL [--header K=V | "
                        "--header-env K=ENVVAR], --telegram-bot-token-env VAR --chat-id ID, or --openclaw.")
    res["configured"] = [T.public(t) for t in new_targets]
    if test:
        for t in new_targets:
            r = test_ping(t, retries=4 if t["kind"] == "openclaw" else 1)
            res["tests"].append(r)
            if not r.get("ok"):
                res["ok"] = False
                if t["kind"] == "openclaw":
                    res["notes"].append("OpenClaw did not accept the test ping. Is the Gateway running? It hot-reloads "
                                        "hooks; otherwise restart it (`openclaw gateway restart`) and run "
                                        "`gotoquill connect --test`.")
    if new_targets:
        res["notes"].append("request_signature now uses these targets automatically when no hooks are passed. "
                            "Webhook receivers can verify X-Gotoquill-Signature (HMAC-SHA256 of '<timestamp>.<body>').")
    return res


def run_tests() -> dict:
    ts = T.targets()
    out = [test_ping(t, retries=1) for t in ts]
    return {"ok": bool(ts) and all(r.get("ok") for r in out), "tests": out}
