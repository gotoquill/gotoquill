"""Runtime configuration (environment variables, all optional). Gotoquill is local-only."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .envcompat import default_data_dir, env_bool, env_get, env_int


@dataclass
class Settings:
    # Working copies of pending requests live here (not the output files, those go next to your PDF).
    data_dir: Path = field(default_factory=default_data_dir)
    default_ttl_minutes: int = field(default_factory=lambda: env_int("TTL_MINUTES", 30))
    max_ttl_minutes: int = field(default_factory=lambda: env_int("MAX_TTL_MINUTES", 1440))
    max_pdf_bytes: int = field(default_factory=lambda: env_int("MAX_PDF_MB", 50) * 1024 * 1024)
    max_pages: int = field(default_factory=lambda: env_int("MAX_PAGES", 500))
    max_signature_bytes: int = 2 * 1024 * 1024
    share_link: bool = field(default_factory=lambda: env_bool("SHARE_LINK", False))
    share_ttl_minutes: int = field(default_factory=lambda: env_int("SHARE_TTL_MINUTES", 15))
    share_max_bad_attempts: int = 20   # wrong-token requests before a share-link page locks
    share_max_submits: int = 5         # failed sign/decline posts before the link locks
    show_footer: bool = field(default_factory=lambda: env_bool("SHOW_FOOTER", True))
    open_browser: bool = field(default_factory=lambda: env_bool("OPEN_BROWSER", True))
    consent_text: str = field(default_factory=lambda: env_get(
        "CONSENT_TEXT",
        "I agree that my electronic signature is the legal equivalent of my handwritten signature "
        "on this document, and I consent to signing it electronically.",
    ) or "")

    def ensure(self) -> "Settings":
        (self.data_dir / "docs").mkdir(parents=True, exist_ok=True)
        return self


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings().ensure()
    return _settings


def set_settings(s: Settings) -> None:
    global _settings
    _settings = s.ensure()
