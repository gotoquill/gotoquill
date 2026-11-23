"""`return_to`: where the "Back to chat" button on the Signed screen sends the signer, with an
"I signed ✅" reply pre-filled. Only allow-listed schemes; the result is a URL template with {text}.

Accepted forms:
  "whatsapp" | "whatsapp:<phone digits>"      -> https://wa.me/<phone>?text={text}
  "telegram" | "telegram:<bot or username>"   -> https://t.me/<bot>?text={text}  (no name: t.me/share/url)
  "sms" | "sms:<phone>"                        -> sms:<phone>?&body={text}
  a custom https:// or app deep link containing {text}, e.g. "https://chat.example.com/r?msg={text}",
  "slack://channel?team=T1&id=C1" (no {text}: the reply is copied to the clipboard instead).
The template travels inside the page data (sealed/encrypted for link modes), never in the link's cleartext.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .core import SignError

# App deep-link schemes the page may navigate to (mirrored in the pages' JS allowlist).
APP_SCHEMES = ("https", "whatsapp", "tg", "sms", "slack", "discord", "sgnl", "fb-messenger", "msteams", "viber",
               "line", "mailto", "imessage")
MAX_LEN = 500
_PHONE = re.compile(r"^\+?[0-9][0-9 ().-]{4,24}$")
_TG = re.compile(r"^@?[A-Za-z][A-Za-z0-9_]{3,31}$")


def normalize(value: str | None) -> str | None:
    """Validate a return_to value and return the URL template (with {text}) or None."""
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    if len(v) > MAX_LEN or any(ord(c) < 32 or c in "<>\"'`\\" for c in v):
        raise SignError("return_to: invalid value")
    kind, _, arg = v.partition(":")
    k = kind.lower()
    if k == "whatsapp" and not arg.startswith("//"):
        if not arg:
            return "https://wa.me/?text={text}"
        if not _PHONE.match(arg):
            raise SignError("return_to: whatsapp:<phone number with country code>")
        return "https://wa.me/" + re.sub(r"\D", "", arg) + "?text={text}"
    if k == "telegram":
        if not arg:
            return "https://t.me/share/url?url=%20&text={text}"
        if not _TG.match(arg):
            raise SignError("return_to: telegram:<bot or username>")
        return "https://t.me/" + arg.lstrip("@") + "?text={text}"
    if k == "sms" and re.fullmatch(r"\+?\d*\?&body=\{text\}", arg):
        return "sms:" + arg  # already normalized (idempotent)
    if k == "sms" and not arg.startswith("//"):
        if arg and not _PHONE.match(arg):
            raise SignError("return_to: sms:<phone number>")
        return "sms:" + re.sub(r"[^0-9+]", "", arg) + "?&body={text}"
    if " " in v:
        raise SignError("return_to: a link must not contain spaces")
    try:
        u = urlsplit(v)
    except ValueError as e:
        raise SignError("return_to: invalid URL") from e
    if u.scheme.lower() not in APP_SCHEMES:
        raise SignError("return_to must be whatsapp[:phone], telegram[:bot], sms[:phone], or an https:// / app link "
                        "with a {text} placeholder (allowed schemes: " + ", ".join(APP_SCHEMES) + ")")
    if u.scheme.lower() == "https" and not u.netloc:
        raise SignError("return_to: https link needs a host")
    return v


def reply_text(document_name: str, signed: bool = True) -> str:
    return (f"I signed {document_name} ✅ Please send me the signed file." if signed
            else f"I declined {document_name}.")
