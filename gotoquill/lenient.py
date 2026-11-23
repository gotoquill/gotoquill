"""Lenient input handling for the MCP surface, so small/weak models' near-miss arguments still work."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

_PLACEHOLDER = re.compile(r"^\s*$|[<>{}$`]|\bresult\b|request[_ ]?id|uuid|example|xxx|\.\.\.", re.I)
_RID = re.compile(r"req_[0-9a-f]{8,}", re.I)


def clean_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'`":
        s = s[1:-1].strip()
    return s or None


def norm_path(v: Any, *, pdf: bool = True, must_exist: bool = True) -> str | None:
    """Accept '~', relative paths, file:// URLs, quoted strings and a missing .pdf extension."""
    s = clean_str(v)
    if s is None:
        return None
    if s.lower().startswith("file:"):
        u = urlparse(s)
        s = unquote(u.path or s[5:])
        if u.netloc and u.netloc not in ("localhost",):
            s = "//" + u.netloc + s
    p = Path(os.path.expandvars(os.path.expanduser(s)))
    if not p.is_absolute():
        p = Path.cwd() / p
    if pdf and not p.exists() and p.suffix.lower() != ".pdf":
        for c in (p.with_name(p.name + ".pdf"), p.with_name(p.name + ".PDF")):
            if c.exists() or not must_exist:
                p = c
                break
    return str(p.resolve(strict=False))


def as_float(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return float(v)
    try:
        return float(str(v).strip().rstrip("s"))
    except ValueError:
        return default


def as_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).strip()))
    except ValueError:
        return None


def as_bool(v: Any, default: bool | None = None) -> bool | None:
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off", "none", "null"):
        return False
    return default


def as_json(v: Any) -> Any:
    """placements/spots/headers may arrive as a JSON string."""
    if isinstance(v, str):
        s = v.strip()
        if s[:1] in "[{":
            try:
                return json.loads(s)
            except ValueError:
                return v
    return v


def norm_delivery(v: Any, default: str = "link") -> str:
    s = (clean_str(v) or default).lower().replace("_", "-")
    return {"local": "page", "browser": "page", "url": "link", "sealed": "link", "offline": "file",
            "html": "file"}.get(s, s)


def extract_request_id(v: Any) -> str | None:
    """Return a usable id, pulling 'req_...' out of junk like 'request_id=req_ab12...' or a pasted JSON blob."""
    s = clean_str(v)
    if not s:
        return None
    m = _RID.search(s)
    if m:
        return m.group(0)
    return s


def is_placeholder(v: Any) -> bool:
    s = clean_str(v)
    return s is None or (not _RID.search(s) and bool(_PLACEHOLDER.search(s)))
