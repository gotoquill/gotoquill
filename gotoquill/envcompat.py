"""GOTOQUILL_* environment variables with deprecated AGENT_SIGN_* fallbacks.

New code should prefer GOTOQUILL_*. Existing installs that still export AGENT_SIGN_*
keep working until users migrate.
"""
from __future__ import annotations

import os
from pathlib import Path


def env_get(suffix: str, default: str | None = None) -> str | None:
    """Read GOTOQUILL_<suffix>, then deprecated AGENT_SIGN_<suffix>.

    `suffix` is the part after the prefix, e.g. ``RELAY_URL`` or ``DATA_DIR``.
    """
    if suffix.startswith("GOTOQUILL_"):
        suffix = suffix[len("GOTOQUILL_") :]
    elif suffix.startswith("AGENT_SIGN_"):
        suffix = suffix[len("AGENT_SIGN_") :]
    for prefix in ("GOTOQUILL_", "AGENT_SIGN_"):
        if prefix + suffix in os.environ:
            return os.environ[prefix + suffix]
    return default


def env_bool(suffix: str, default: bool = False) -> bool:
    v = env_get(suffix)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def env_int(suffix: str, default: int) -> int:
    v = env_get(suffix)
    if v is None or str(v).strip() == "":
        return default
    return int(v)


def default_data_dir() -> Path:
    """~/.gotoquill, with fallback read of ~/.agent-sign when the new dir does not exist yet."""
    explicit = env_get("DATA_DIR")
    if explicit:
        return Path(explicit).expanduser()
    new = Path("~/.gotoquill").expanduser()
    old = Path("~/.agent-sign").expanduser()
    if new.exists() or not old.exists():
        return new
    return old


def resolve_config_dir() -> Path:
    """Config dir: GOTOQUILL_CONFIG_DIR / AGENT_SIGN_CONFIG_DIR, else platformdirs gotoquill,
    else legacy platformdirs agent-sign / ~/.agent-sign when present.
    """
    explicit = env_get("CONFIG_DIR")
    if explicit:
        return Path(explicit).expanduser()
    from platformdirs import user_config_dir

    new = Path(user_config_dir("gotoquill", appauthor=False))
    if new.exists():
        return new
    old_pd = Path(user_config_dir("agent-sign", appauthor=False))
    if old_pd.exists():
        return old_pd
    old_home = Path("~/.agent-sign").expanduser()
    if old_home.exists() and not new.exists():
        # Older installs sometimes used ~/.agent-sign for both data + config.
        return old_home
    return new
