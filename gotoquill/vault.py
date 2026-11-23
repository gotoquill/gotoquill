"""Saved signatures ("signature vault"), stored only on this computer.

File: <user config dir>/gotoquill/signatures.json (e.g. ~/.config/gotoquill/), permissions 0600.
* If the OS keychain is available (via `keyring`: macOS Keychain, Windows Credential Manager,
  Linux Secret Service), the file is encrypted (Fernet / AES) with a random key kept in the keychain.
* Otherwise the file is a plain local JSON file (still 0600, readable by your user account only).

Saved images are only ever sent to the signing page the human has open. No agent tool returns them,
and they can only be applied by a click on that page.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import stat
import threading
from datetime import datetime, timezone
from pathlib import Path

KEYRING_SERVICE = "gotoquill"
KEYRING_SERVICE_LEGACY = "agent-sign"
KEYRING_USER = "signature-vault-key"
NAMES = ("signature", "initials")
_lock = threading.Lock()


class VaultError(Exception):
    pass


def config_dir() -> Path:
    from .envcompat import resolve_config_dir
    return resolve_config_dir()


def vault_path() -> Path:
    return config_dir() / "signatures.json"


def _keyring_disabled() -> bool:
    from .envcompat import env_bool
    return env_bool("NO_KEYRING", False)


def _keyring():
    if _keyring_disabled():
        return None
    try:
        import keyring
        from keyring.backends import fail
        kr = keyring.get_keyring()
        if isinstance(kr, fail.Keyring) or getattr(kr, "priority", 1) <= 0:
            return None
        return keyring
    except Exception:  # noqa: BLE001
        return None


def _get_key(create: bool, user: str = KEYRING_USER) -> bytes | None:
    kr = _keyring()
    if kr is None:
        return None
    try:
        k = kr.get_password(KEYRING_SERVICE, user)
        if not k:
            # Deprecated service name from agent-sign installs.
            try:
                k = kr.get_password(KEYRING_SERVICE_LEGACY, user)
            except Exception:  # noqa: BLE001
                k = None
        if not k and create:
            from cryptography.fernet import Fernet
            k = Fernet.generate_key().decode()
            kr.set_password(KEYRING_SERVICE, user, k)
        return k.encode() if k else None
    except Exception:  # noqa: BLE001  (locked / unavailable keychain)
        return None


def keyring_status() -> dict:
    kr = _keyring()
    if kr is None:
        return {"available": False, "backend": None}
    return {"available": True, "backend": type(kr.get_keyring()).__module__ + "." + type(kr.get_keyring()).__name__}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_name(path.name + "." + secrets.token_hex(4) + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _read_raw() -> dict | None:
    p = vault_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise VaultError(f"cannot read {p}: {e}") from e


def _load() -> dict:
    raw = _read_raw()
    if not raw:
        return {}
    if raw.get("encrypted"):
        key = _get_key(create=False)
        if not key:
            raise VaultError("saved signatures are encrypted but the OS keychain key is not available")
        from cryptography.fernet import Fernet, InvalidToken
        try:
            return json.loads(Fernet(key).decrypt(raw["data"].encode()))
        except (InvalidToken, ValueError) as e:
            raise VaultError("could not decrypt saved signatures (keychain key changed?)") from e
    return raw.get("signatures", {})


def _store(sigs: dict) -> None:
    p = vault_path()
    if not sigs:
        if p.exists():
            p.unlink()
        return
    key = _get_key(create=True)
    if key:
        from cryptography.fernet import Fernet
        doc = {"version": 1, "encrypted": True, "key_location": f"OS keychain ({KEYRING_SERVICE}/{KEYRING_USER})",
               "data": Fernet(key).encrypt(json.dumps(sigs).encode()).decode()}
    else:
        doc = {"version": 1, "encrypted": False,
               "note": "Plain local file (no OS keychain found). Protected only by file permissions 0600.",
               "signatures": sigs}
    _write(p, json.dumps(doc, indent=1))


def _meta(name: str, s: dict) -> dict:
    return {"name": name, "method": s.get("method"), "signer_name": s.get("signer_name"),
            "saved_at": s.get("saved_at"), "image_bytes": len(base64.b64decode(s["png"])) if s.get("png") else 0}


# ---------------- public API ----------------
def save(name: str, png: bytes, method: str, signer_name: str | None) -> dict:
    if name not in NAMES:
        raise VaultError(f"name must be one of {NAMES}")
    with _lock:
        sigs = _load()
        sigs[name] = {"png": base64.b64encode(png).decode(), "method": method, "signer_name": signer_name,
                      "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
        _store(sigs)
        return _meta(name, sigs[name])


def get_png(name: str) -> bytes:
    """Internal only (stamping after a human click). Never return this to an agent."""
    s = _load().get(name)
    if not s:
        raise VaultError(f"no saved signature named '{name}'")
    return base64.b64decode(s["png"])


def previews() -> list[dict]:
    """Metadata + image data URL, for the human's signing page only."""
    try:
        sigs = _load()
    except VaultError:
        return []
    return [{**_meta(n, s), "image": "data:image/png;base64," + s["png"]} for n, s in sigs.items()]


def delete(name: str | None = None) -> list[str]:
    with _lock:
        try:
            sigs = _load()
        except VaultError:
            sigs = None
        if sigs is None or name is None:  # delete everything (also unreadable files)
            removed = list(sigs or {}) or (["(unreadable file)"] if vault_path().exists() else [])
            if vault_path().exists():
                vault_path().unlink()
            return removed
        if name not in sigs:
            return []
        del sigs[name]
        _store(sigs)
        return [name]


def info() -> dict:
    """Path + metadata only (no images). Used by `gotoquill signature show`."""
    p = vault_path()
    out = {"path": str(p), "exists": p.exists(), "keychain": keyring_status(), "signatures": []}
    if p.exists():
        out["permissions"] = oct(stat.S_IMODE(p.stat().st_mode))
        raw = _read_raw() or {}
        out["encrypted"] = bool(raw.get("encrypted"))
        try:
            out["signatures"] = [_meta(n, s) for n, s in _load().items()]
        except VaultError as e:
            out["error"] = str(e)
    return out
