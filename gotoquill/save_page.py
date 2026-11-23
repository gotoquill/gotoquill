"""Token-gated browser save page. Keep static/save.html in sync with the Worker copy."""
from __future__ import annotations

import html
import re
import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi.responses import HTMLResponse

DOWNLOAD_HEADERS = {
    "cache-control": "private, no-store",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}


def safe_filename(name: str) -> str:
    return re.sub(r'[\x00-\x1f\x7f/\\"<>:|?*\u202a-\u202e\u2066-\u2069]', '_', name) or 'signed.pdf'


def attachment_disposition(name: str) -> str:
    fallback = re.sub(r'[^\w.\- ]+', '_', name, flags=re.ASCII)
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(name, safe="")}'


def save_page(pdf_url: str, filename: str, *, head: bool = False) -> HTMLResponse:
    nonce = secrets.token_hex(16)
    template = Path(__file__).with_name('static').joinpath('save.html').read_text(encoding='utf-8')
    values = {'__NONCE__': nonce, '__PDF_URL__': html.escape(pdf_url, quote=True),
              '__FILENAME__': html.escape(filename, quote=True)}
    body = re.sub(r'__NONCE__|__PDF_URL__|__FILENAME__', lambda match: values[match[0]], template)
    return HTMLResponse('' if head else body, headers={
        **DOWNLOAD_HEADERS,
        'x-frame-options': 'DENY',
        'content-length': str(len(body.encode('utf-8'))),
        'content-security-policy': (
            f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        ),
    })
