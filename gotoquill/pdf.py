"""PDF helpers: validation, preview rendering, signature stamping (pdfplumber / pypdf / reportlab / pypdfium2)."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from . import pdfdoc
from .labels import is_id_label, is_hebrew_date, variants


class PdfError(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_pdf(data: bytes, max_pages: int) -> dict:
    if not data.startswith(b"%PDF"):
        raise PdfError("document is not a PDF")
    try:
        doc = pdfdoc.Document.open(data)
        doc.page_count  # noqa: B018 - force parsing the page tree
    except Exception as e:  # noqa: BLE001
        raise PdfError(f"cannot open PDF: {e}") from e
    with doc:
        if doc.needs_pass:
            raise PdfError("encrypted PDFs are not supported")
        if doc.page_count > max_pages:
            raise PdfError(f"PDF has {doc.page_count} pages; limit is {max_pages}")
        fields = []
        sizes = []
        for p in doc:
            sizes.append([round(v, 2) for v in p.display_size])
            for w in p.widgets() or []:
                fields.append({"name": w.field_name, "page": p.number + 1, "rect": [round(v, 2) for v in w.rect]})
        return {"page_count": doc.page_count, "page_sizes": sizes, "fields": fields}


def render_page_png(data: bytes, page: int, width_px: int = 1000) -> bytes:
    with pdfdoc.Document.open(data) as doc:
        if not 1 <= page <= doc.page_count:
            raise PdfError("page out of range")
        p = doc[page - 1]
        zoom = max(0.2, min(3.0, width_px / p.display_size[0]))
    return pdfdoc.render_png(data, page - 1, zoom)


def resolve_rect(doc: "pdfdoc.Document", pl: dict) -> tuple[int, "pdfdoc.Rect"]:
    """Return (0-based page index, rect) for a placement. Coordinates are PDF points, origin top-left."""
    if pl.get("field_name"):
        for p in doc:
            for w in p.widgets() or []:
                if w.field_name == pl["field_name"]:
                    return p.number, pdfdoc.Rect(w.rect)
        raise PdfError(f"form field not found: {pl['field_name']}")
    page = int(pl.get("page", 1))
    if not 1 <= page <= doc.page_count:
        raise PdfError(f"page {page} out of range (1..{doc.page_count})")
    x, y, w = float(pl["x"]), float(pl["y"]), float(pl.get("width", 180))
    h = float(pl.get("height") or w / 3)
    return page - 1, pdfdoc.Rect(x, y, x + w, y + h)


def _obstacles(page: "pdfdoc.Page") -> list["pdfdoc.Rect"]:
    obs = [pdfdoc.Rect(w[:4]) for w in page.get_text("words")]
    for d in page.get_drawings():
        r = pdfdoc.Rect(d["rect"])
        if r.height < 1:  # horizontal rules: give them some thickness
            r.y0 -= 1; r.y1 += 1
        obs.append(r)
    return obs


def free_line_rect(page: "pdfdoc.Page", anchor: "pdfdoc.Rect", height: float = 11,
                   width: float | None = None, max_shift: float = 90) -> "pdfdoc.Rect":
    """Find a rect for a small text line under `anchor` that doesn't overlap existing page content.

    Tries directly below the anchor, then moves down (past labels/lines) and finally above it.
    """
    w = width or max(anchor.width, 160)
    x0 = anchor.x0
    x1 = min(page.rect.x1 - 18, x0 + w)
    from .placement import id_areas
    obs = [o for o in _obstacles(page) if not o.is_empty] + id_areas(page)

    def free(r):
        return all(not r.intersects(o) for o in obs)

    y = anchor.y1 + 2
    while y + height <= min(page.rect.y1 - 6, anchor.y1 + max_shift):
        r = pdfdoc.Rect(x0, y, x1, y + height)
        if free(r):
            return r
        y += 1
    y = anchor.y0 - height - 2
    while y >= max(6, anchor.y0 - max_shift):
        r = pdfdoc.Rect(x0, y, x1, y + height)
        if free(r):
            return r
        y -= 1
    return pdfdoc.Rect(x0, anchor.y1 + 2, x1, anchor.y1 + 2 + height)


DATE_WORDS = ("date", "dated", "תאריך", "fecha", "datum", "data")
_NOT_DATE = re.compile(r"(up|candi|vali|man|accommo|consoli|liqui|sen)date")
_ISO_LOCALES = ("sv", "ja", "zh", "ko", "lt", "hu", "fr-ca", "en-ca")


def _is_date_word(t: str) -> bool:
    if is_id_label(t):
        return False
    if is_hebrew_date(t):
        return True
    t = (t or "").strip().strip(":：.-_*()[]").lower()
    # Hebrew text in PDFs is often stored in visual order, so also accept the reversed word.
    return any(x in DATE_WORDS for x in (t, t[::-1]))


def is_date_field(name: str | None, label: str | None = None) -> bool:
    if is_id_label(f"{name or ''} {label or ''}"):
        return False
    for t in (name, label):
        t = (t or "").lower()
        if not t:
            continue
        if any("תאריכ" in v for v in variants(t)) or "fecha" in t or "datum" in t or ("date" in t and not _NOT_DATE.search(t)):
            return True
    return False




def signer_zone(ctx: dict | None):
    """tzinfo from the signing page's IANA zone, else its UTC offset (minutes east of UTC), else UTC."""
    ctx = ctx or {}
    tz = ctx.get("timezone")
    if tz:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(str(tz)), str(tz)
        except Exception:  # noqa: BLE001
            pass
    off = ctx.get("utc_offset_minutes")
    try:
        off = int(off)
        if -14 * 60 <= off <= 14 * 60:
            sign = "+" if off >= 0 else "-"
            label = f"UTC{sign}{abs(off) // 60:02d}:{abs(off) % 60:02d}"
            return timezone(timedelta(minutes=off)), label
    except (TypeError, ValueError):
        pass
    return timezone.utc, "UTC"


def default_date_format(locale: str | None) -> str:
    loc = (locale or "").lower().replace("_", "-")
    if not loc:
        return "%d %b %Y"
    if loc in ("en-us", "en-ph", "en") or loc.startswith("en-us"):
        return "%m/%d/%Y"
    if any(loc == x or loc.startswith(x + "-") for x in _ISO_LOCALES):
        return "%Y-%m-%d"
    if loc.startswith(("de", "ru", "pl", "fi", "cs", "tr", "uk", "nb", "da")):
        return "%d.%m.%Y"
    return "%d/%m/%Y"


_TOKENS = [("YYYY", "%Y"), ("MMMM", "%B"), ("MMM", "%b"), ("MM", "%m"), ("DD", "%d"), ("YY", "%y"),
           ("HH", "%H"), ("mm", "%M")]


def to_strftime(fmt: str | None, locale: str | None = None) -> str:
    """Accepts strftime ('%d/%m/%Y'), tokens ('DD/MM/YYYY'), or None/'auto'/'locale' (from the signer's locale)."""
    if not fmt or fmt in ("auto", "locale"):
        return default_date_format(locale)
    if "%" in fmt:
        return fmt
    out, i = "", 0
    while i < len(fmt):
        for tok, rep in _TOKENS:
            if fmt.startswith(tok, i):
                out += rep; i += len(tok); break
        else:
            out += fmt[i]; i += 1
    return out


def _rules(page) -> list["pdfdoc.Rect"]:
    out = []
    for d in page.get_drawings():
        r = pdfdoc.Rect(d["rect"])
        if r.width >= 30 and r.height <= 2.5:
            out.append(r)
    return out


def find_date_spot(page, sig_rect: "pdfdoc.Rect") -> "pdfdoc.Rect | None":
    """Find a 'Date' / 'Date:' / 'תאריך' label near the signature with a ruled line above it or next to it.

    Returns the rect to write the date in (sitting on the line), or None."""
    from .placement import id_areas
    protected = id_areas(page)
    words = page.get_text("words")
    labels = [pdfdoc.Rect(w[:4]) for w in words if _is_date_word(w[4])]
    if not labels:
        return None
    rules = _rules(page)
    near = pdfdoc.Rect(sig_rect.x0 - 40, sig_rect.y0 - 120, page.rect.x1, sig_rect.y1 + 140)
    best = None
    for lab in labels:
        if not near.intersects(lab):
            continue
        dist = abs(lab.y0 - sig_rect.y1)
        cands = []
        for r in rules:
            # line above the label (label printed under the line), horizontally overlapping
            if 0 <= lab.y0 - r.y1 <= 14 and r.x0 - 4 <= lab.x0 <= r.x1:
                cands.append((0, pdfdoc.Rect(r.x0, r.y0 - 14, r.x1, r.y0)))
            # same row: line to the right (LTR 'Date: ____') or left (RTL '____ :תאריך')
            elif abs(r.y1 - lab.y1) <= 5:
                if r.x0 >= lab.x1 - 2 and r.x0 - lab.x1 <= 40:
                    cands.append((1, pdfdoc.Rect(r.x0, r.y0 - 14, r.x1, r.y0)))
                elif r.x1 <= lab.x0 + 2 and lab.x0 - r.x1 <= 40:
                    cands.append((1, pdfdoc.Rect(r.x0, r.y0 - 14, r.x1, r.y0)))
        if not cands:
            # label with a blank to its right on the same row and no line ('Date: ' then empty space)
            if lab.x1 + 80 < page.rect.x1:
                r = pdfdoc.Rect(lab.x1 + 4, lab.y0, min(page.rect.x1 - 18, lab.x1 + 120), lab.y1)
                if all(not r.intersects(pdfdoc.Rect(w[:4])) for w in words):
                    cands.append((2, r))
        for pri, r in cands:
            if any(r.intersects(area) for area in protected):
                continue
            key = (pri, dist)
            if best is None or key < best[0]:
                best = (key, r)
    return best[1] if best else None


def _write_date(page, rect: "pdfdoc.Rect", text: str, rtl: bool = False) -> None:
    from reportlab.pdfbase.pdfmetrics import getAscentDescent
    pad = min(2.0, rect.width / 8, rect.height / 8)
    ascent, descent = getAscentDescent(pdfdoc.FONT, 1)
    fs = min(11.0, (rect.width - 2 * pad) / max(pdfdoc.text_length(text, 1), 0.001),
             (rect.height - 2 * pad) / (ascent - descent))
    tw = pdfdoc.text_length(text, fs)
    x = rect.x1 - tw - pad if rtl else rect.x0 + pad
    baseline = rect.y0 + pad + (rect.height - 2 * pad - (ascent - descent) * fs) / 2 + ascent * fs
    page.insert_text((x, baseline), text, fontsize=fs)


def _page_is_rtl(page) -> bool:
    t = page.get_text()
    heb = sum(1 for ch in t if "\u0590" <= ch <= "\u05ff" or "\u0600" <= ch <= "\u06ff")
    lat = sum(1 for ch in t if ch.isascii() and ch.isalpha())
    return heb > lat


def fill_date_fields(doc, text: str) -> int:
    """Fill empty text form fields whose name or label is a date (incl. Hebrew). Returns how many."""
    from .placement import id_areas
    n = 0
    for p in doc:
        protected = id_areas(p)
        for w in list(p.widgets() or []):
            if w.field_type != pdfdoc.WIDGET_TEXT or (w.field_value or "").strip():
                continue
            if is_date_field(w.field_name, getattr(w, "field_label", None)) and not any(w.rect.intersects(r) for r in protected):
                p.delete_widget(w)
                _write_date(p, w.rect, text)
                n += 1
    return n


def stamp_plan(data: bytes, placements: list[dict]) -> dict:
    """Resolve geometry once, in unrotated CropBox points (top-left origin).

    Both stamp engines consume these rectangles, typography and date formats.
    Optional lines reserve their full area before the signer's name/date is known.
    """
    from .placement import plan, id_areas
    if placements:
        placements, _ = plan(data, placements, add_date=any(p.get("add_date") for p in placements))
    zone_names = {}
    if any("%Z" in str(p.get("date_format", "")) for p in placements):
        # Browser Intl abbreviations differ from Python (e.g. GMT+9 vs JST).
        # Ship exact names for the maximum offline signing window, including DST changes.
        from zoneinfo import ZoneInfo, available_timezones
        now = utcnow()
        for name in sorted(available_timezones()):
            zone = ZoneInfo(name)
            names = {}
            for day in range(-1, 32):
                local = (now + timedelta(days=day)).astimezone(zone)
                names[str(int(local.utcoffset().total_seconds() / 60))] = local.tzname()
            zone_names[name] = names
    ops, removals = [], []
    with pdfdoc.Document.open(data) as doc:
        for pl in placements:
            idx, rect = resolve_rect(doc, pl)
            page = doc[idx]
            fmt = pl.get("date_format")
            # Auto dates inherit the signature's requested format.
            if pl.get("auto_date") and not fmt:
                fmt = next((p.get("date_format") for p in placements if p.get("date_format")), None)
            for w in page.widgets() or []:
                if w.field_name == pl.get("field_name") or w.rect.intersects(rect):
                    removals.append({"page": idx, "name": w.field_name, "rect": list(w.rect)})
            pad = min(2.0, rect.width / 8, rect.height / 8)
            kind = pl.get("kind", "signature")
            op = {"kind": "date" if kind == "date" else "signature", "page": idx,
                  "rect": list(rect), "pad": pad, "date_format": fmt}
            ops.append(op)
            if kind == "date":
                continue
            protected = id_areas(page)
            line = free_line_rect(page, rect, height=9.5, width=max(rect.width, 120), max_shift=40)
            if not any(line.intersects(r) for r in protected):
                ops.append({"kind": "signed_by", "page": idx, "rect": list(line),
                            "date_format": fmt, "font_size": 7, "min_font_size": 5,
                            "baseline_inset": 2, "color": [0.45, 0.45, 0.47]})
            if pl.get("add_date") and pl.get("proof_line", True):
                # Reserve a separate proof line so opting into Signed by cannot overlap it.
                anchor = pdfdoc.Rect(rect.x0, rect.y0, rect.x1, max(rect.y1, line.y1))
                proof = free_line_rect(page, anchor, height=11)
                if not any(proof.intersects(r) for r in protected):
                    ops.append({"kind": "proof", "page": idx, "rect": list(proof),
                                "date_format": "%d %b %Y, %H:%M", "font_size": 8,
                                "baseline_inset": 2.5, "color": [0.25, 0.25, 0.25]})
        return {"version": 1, "coordinates": "cropbox-top-left", "font": "Helvetica",
                "ascent": 0.718, "descent": -0.207, "date_font_size": 11,
                "operations": ops, "remove_widgets": removals, "zone_names": zone_names}


def stamp(data: bytes, placements: list[dict], signature_png: bytes, signed_at: datetime,
          signer_name: str | None, request_id: str, signer: dict | None = None, signed_by_line: bool = False,
          *, plan: dict | None = None) -> bytes:
    """Stamp the authoritative PDF using the same plan supplied to the offline browser."""
    plan = plan or stamp_plan(data, placements)
    tz, tz_label = signer_zone(signer)
    local = signed_at.astimezone(tz)
    locale = (signer or {}).get("locale")
    with pdfdoc.Document.open(data) as doc:
        for rem in plan["remove_widgets"]:
            page = doc[rem["page"]]
            for w in list(page.widgets() or []):
                if w.field_name == rem["name"] and list(w.rect) == rem["rect"]:
                    page.delete_widget(w)
        for op in plan["operations"]:
            page, rect = doc[op["page"]], pdfdoc.Rect(op["rect"])
            kind = op["kind"]
            if kind == "signature":
                pad = op["pad"]
                page.insert_image(pdfdoc.Rect(rect.x0 + pad, rect.y0 + pad, rect.x1 - pad, rect.y1 - pad), signature_png)
                continue
            if kind == "signed_by" and not signed_by_line:
                continue
            text = local.strftime(to_strftime(op.get("date_format"), locale)).encode("cp1252", errors="replace").decode("cp1252")
            if kind == "date":
                _write_date(page, rect, text)
                continue
            text = signed_by_text(signer_name, text) if kind == "signed_by" else f"Signed {text} ({tz_label})"
            text = text.encode("cp1252", errors="replace").decode("cp1252")
            fs = op["font_size"]
            if kind == "signed_by":
                while fs > op["min_font_size"] and pdfdoc.text_length(text, fs) > rect.width:
                    fs -= 0.25
            page.insert_text((rect.x0, rect.y1 - op["baseline_inset"]), text, fontsize=fs, color=op["color"])
        return doc.tobytes(metadata={"/Producer": "gotoquill", "/Keywords": f"gotoquill request {request_id}"})


def signed_by_text(name: str | None, date_text: str) -> str:
    name = " ".join((name or "").split())[:80]
    return f"Signed by {name} \u00b7 {date_text}" if name else f"Signed \u00b7 {date_text}"


def _signed_by(page, rect, name: str | None, date_text: str) -> None:
    """One small grey line right under the signature spot, shrunk to the spot's width, never over other content."""
    text = signed_by_text(name, date_text)
    w = max(rect.width, 120.0)
    fs = 7.0
    while fs > 5.0 and pdfdoc.text_length(text, fs) > w:
        fs -= 0.25
    d = free_line_rect(page, rect, height=fs + 2.5, width=min(w, pdfdoc.text_length(text, fs) + 2), max_shift=40)
    from .placement import id_areas
    if any(d.intersects(r) for r in id_areas(page)):
        return
    page.insert_text((d.x0, d.y1 - 2.0), text, fontsize=fs, color=(0.45, 0.45, 0.47))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
