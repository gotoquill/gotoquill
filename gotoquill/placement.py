"""Where the signature (and date) go: AcroForm fields, else labels ('Signature', 'חתימת המבוטח', 'Firma', ...)
next to an empty drawn box or a ruled line, in either reading direction; else a guess at the bottom of the last
page. Also renders preview PNGs with the chosen spots highlighted, and a small PNG of the signed spots."""
from __future__ import annotations

import re
from pathlib import Path

from . import pdfdoc

from . import pdf
from .labels import MAX_LABEL_WORDS, normalize_label, is_id_label, is_hebrew_signature, logical_label, role_hint

# prefixes of a "signature" word, per language (lower case). Also tested reversed (RTL text stored visually).
SIG_PREFIXES = ("sign", "firma", "unterschrift", "unterzeichn", "assinatura", "handtekening", "ondertekening",
                "podpis", "подпис", "توقيع", "署名", "签名", "簽名", "서명", "imza", "signatur", "allekiri")
SIG_EXCLUDE = ("signif", "signal", "signag", "signor")
_PUNCT = ":：.-_*()[]\"'״׳,;|/\\"


def _norm(t: str) -> str:
    return (t or "").strip().strip(_PUNCT).lower()


def is_sig_word(t: str) -> bool:
    if pdf._is_date_word(t):
        return False
    if is_hebrew_signature(t):
        return True
    t = _norm(normalize_label(t))
    if not t or is_id_label(t):
        return False
    for x in (t, t[::-1]):
        if x.startswith(SIG_PREFIXES) and not x.startswith(SIG_EXCLUDE):
            return True
    return False


def is_date_word(t: str) -> bool:
    return pdf._is_date_word(t)


def _is_rtl_text(t: str) -> bool:
    return any("\u0590" <= ch <= "\u06ff" for ch in t or "")


# ------------------------------------------------------------------ page geometry
def _segments(page) -> tuple[list, list, list]:
    """(horizontal segments [(x0, x1, y)], vertical [(y0, y1, x)], rects from 're'/'qu' items)."""
    hs, vs, rects = [], [], []
    for d in page.get_drawings():
        fill = d.get("fill")
        dark_fill = fill is not None and min(fill) < 0.8
        for it in d["items"]:
            op = it[0]
            if op == "l":
                a, b = it[1], it[2]
                if abs(a.y - b.y) < 1.5 and abs(a.x - b.x) >= 8:
                    hs.append((min(a.x, b.x), max(a.x, b.x), (a.y + b.y) / 2))
                elif abs(a.x - b.x) < 1.5 and abs(a.y - b.y) >= 6:
                    vs.append((min(a.y, b.y), max(a.y, b.y), (a.x + b.x) / 2))
            elif op in ("re", "qu"):
                r = pdfdoc.Rect(it[1].rect if op == "qu" else it[1])
                if r.height <= 2.5 and r.width >= 8:  # thin filled rect = ruled line
                    hs.append((r.x0, r.x1, (r.y0 + r.y1) / 2))
                    continue
                if not dark_fill:
                    rects.append(r)
                hs += [(r.x0, r.x1, r.y0), (r.x0, r.x1, r.y1)]
                vs += [(r.y0, r.y1, r.x0), (r.y0, r.y1, r.x1)]
    return hs, vs, rects


def _cells(hs, vs, page_rect) -> list:
    """Rectangles closed by line segments (stand-alone boxes and table cells)."""
    out = []
    vs = sorted(vs, key=lambda v: v[2])[:600]
    for i, (a0, a1, ax) in enumerate(vs):
        for b0, b1, bx in vs[i + 1:]:
            if bx - ax < 25:
                continue
            if bx - ax > 460:
                break
            y0, y1 = max(a0, b0), min(a1, b1)
            if y1 - y0 < 8:
                continue
            ys = sorted({round(h[2], 1) for h in hs
                         if h[0] <= ax + 3 and h[1] >= bx - 3 and y0 - 2 <= h[2] <= y1 + 2})
            for u, w in zip(ys, ys[1:]):
                if 8 <= w - u <= 160:
                    out.append(pdfdoc.Rect(ax, u, bx, w))
    return out


def _uniq(rects) -> list:
    out = []
    for r in rects:
        if not any(abs(r.x0 - o.x0) < 2 and abs(r.y0 - o.y0) < 2 and abs(r.x1 - o.x1) < 2 and abs(r.y1 - o.y1) < 2
                   for o in out):
            out.append(r)
    return out


class PageInfo:
    def __init__(self, page):
        self.page = page
        self.rect = page.rect
        self.words = []
        for w in page.get_text("words"):
            # pdfdoc returns RTL words in reading order. Split attached underscores
            # in visual order so their inferred writing line stays on the correct side.
            visual = w[4][::-1] if _is_rtl_text(w[4]) else w[4]
            match = re.search(r"_{3,}", visual)
            if match and match.group() != visual:
                cw = (w[2] - w[0]) / len(visual)
                for start, end in ((0, match.start()), (match.start(), match.end()), (match.end(), len(visual))):
                    if start == end:
                        continue
                    value = visual[start:end]
                    if _is_rtl_text(value):
                        value = value[::-1]
                    self.words.append((w[0] + start * cw, w[1], w[0] + end * cw, w[3], value, *w[5:]))
            else:
                self.words.append(w)
        self.rtl = pdf._page_is_rtl(page) if self.words else False
        hs, vs, rects = _segments(page)
        under = [pdfdoc.Rect(w[:4]) for w in self.words if re.fullmatch(r"_{3,}", w[4] or "")]
        self.text_words = [w for w in self.words if not re.fullmatch(r"_{3,}", w[4] or "")]
        pw, ph = self.rect.width, self.rect.height
        boxes = [r for r in _uniq(rects + _cells(hs, vs, self.rect))
                 if 25 <= r.width <= min(460, pw * 0.8) and 8 <= r.height <= min(160, ph * 0.3)]
        self.boxes = boxes
        rules = []
        for x0, x1, y in hs:
            if x1 - x0 < 40 or x1 - x0 > pw * 0.85:
                continue
            if any(abs(y - b.y0) < 2.5 or abs(y - b.y1) < 2.5 for b in boxes if b.x0 - 3 <= x0 and x1 <= b.x1 + 3):
                continue  # a box edge, not a stand-alone line
            rules.append(pdfdoc.Rect(x0, y - 0.5, x1, y + 0.5))
        for u in under:
            rules.append(pdfdoc.Rect(u.x0, u.y1 - 1, u.x1, u.y1))
        self.rules = _uniq(rules)
        self.id_targets = []
        for lab, text, grp in _labels(self, is_id_label):
            if is_sig_word(text):  # combined "signature and ID" still labels signature ink
                continue
            cs = sorted(_candidates(self, lab, text, grp, "date"), key=lambda c: c[0])
            if cs:
                self.id_targets.append(cs[0][2])
        for w in page.widgets() or []:
            if is_id_label(f"{w.field_name or ''} {getattr(w, 'field_label', '') or ''}"):
                self.id_targets.append(pdfdoc.Rect(w.rect))

    def empty(self, r: "pdfdoc.Rect", ignore=()) -> bool:
        inner = pdfdoc.Rect(r.x0 + 1.5, r.y0 + 1.5, r.x1 - 1.5, r.y1 - 1.5)
        for w in self.text_words:
            if w in ignore:
                continue
            c = pdfdoc.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
            if c in inner:
                return False
        return True

    def space_above(self, x0, x1, y, want=42.0) -> float:
        """Free height above y (between x0 and x1) up to `want`."""
        top = y - want
        for w in self.text_words:
            if w[2] > x0 and w[0] < x1 and w[3] <= y - 1 and w[3] > top:
                top = w[3]
        for r in self.rules + self.boxes:
            if r.x1 > x0 and r.x0 < x1 and r.y1 <= y - 3 and r.y1 > top:
                top = r.y1
        return y - top


def _labels(pi: PageInfo, test) -> list[tuple["pdfdoc.Rect", str, list]]:
    """Short label phrases containing a matching word: (rect, text, words)."""
    lines: dict = {}
    for w in pi.text_words:
        lines.setdefault((w[5], w[6]), []).append(w)
    out = []
    other = is_sig_word if test is is_date_word else is_date_word
    for ws in lines.values():
        ws = sorted(ws, key=lambda w: w[0])
        phrase = " ".join(w[4] for w in ws)
        if len(normalize_label(phrase).split()) > MAX_LABEL_WORDS:
            continue
        if _is_rtl_text(phrase) or test is is_id_label:
            # Separate labels on one row at visible gaps, while preserving spaced letters.
            groups = []
            for w in ws:
                if (not groups or w[0] - groups[-1][-1][2] > 8 or
                        (":" in w[4] and ":" in groups[-1][-1][4] and
                         ((is_date_word(w[4]) and is_sig_word(groups[-1][-1][4])) or
                          (is_sig_word(w[4]) and is_date_word(groups[-1][-1][4]))))):
                    groups.append([])
                groups[-1].append(w)
            for grp in groups:
                text = " ".join(w[4] for w in grp)
                if not test(text):
                    continue
                r = pdfdoc.Rect(grp[0][:4])
                for w in grp[1:]:
                    r |= pdfdoc.Rect(w[:4])
                out.append((r, text, grp))
            continue
        for i, w in enumerate(ws):
            if not test(w[4]):
                continue
            grp = [w]
            for j in range(i - 1, -1, -1):  # extend left
                if grp[0][0] - ws[j][2] > 8 or other(ws[j][4]) or test(ws[j][4]):
                    break
                grp.insert(0, ws[j])
            for j in range(i + 1, len(ws)):
                if ws[j][0] - grp[-1][2] > 8 or other(ws[j][4]) or test(ws[j][4]):
                    break
                grp.append(ws[j])
            r = pdfdoc.Rect(grp[0][:4])
            for g in grp:
                r |= pdfdoc.Rect(g[:4])
            text = " ".join(g[4] for g in (reversed(grp) if _is_rtl_text(w[4]) else grp))
            if not any(r == o[0] for o in out):
                out.append((r, text, grp))
    return out


def _vover(a, b) -> float:
    return max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))


def _hover(a, b) -> float:
    return max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))


def _candidates(pi: PageInfo, lab, text, grp, kind: str) -> list[tuple[float, str, "pdfdoc.Rect", "pdfdoc.Rect"]]:
    """(score, target type, target rect, rect to put the signature/date in)."""
    cands = []
    lh = max(lab.height, 6)
    for b in pi.boxes:
        if any(b.intersects(r) for r in getattr(pi, "id_targets", [])):
            continue
        if not pi.empty(b, ignore=grp):
            continue
        inside = b.contains(lab)
        if inside:  # label printed in the box corner: use the free part of the box
            if b.y1 - lab.y1 >= 14:
                cands.append((1, "box", b, pdfdoc.Rect(b.x0, lab.y1, b.x1, b.y1)))
            continue
        if not pi.empty(b):
            continue
        if _vover(b, lab) >= 0.5 * lh:  # beside, either direction
            g = b.x0 - lab.x1 if b.x0 >= lab.x1 - 2 else lab.x0 - b.x1 if b.x1 <= lab.x0 + 2 else None
            if g is not None and g <= 130:
                cands.append((max(g, 0), "box", b, b))
        elif _hover(b, lab) > 0:
            if 0 <= lab.y0 - b.y1 <= 28:  # label under the box
                cands.append((lab.y0 - b.y1 + 4, "box", b, b))
            elif 0 <= b.y0 - lab.y1 <= 28:  # label above the box
                cands.append((b.y0 - lab.y1 + 8, "box", b, b))
    for r in pi.rules:
        if any(r.intersects(b) for b in getattr(pi, "id_targets", [])):
            continue
        y = r.y0
        if _hover(r, lab) > 0 and -1 <= lab.y0 - y <= 16:  # line above the label
            cands.append((lab.y0 - y, "line", r, _above_line(pi, r, kind)))
        elif _is_rtl_text(text) and _hover(r, lab) > 0 and 0 <= y - lab.y1 <= 28:
            cands.append((y - lab.y1 + 8, "line", r, _above_line(pi, r, kind)))
        elif abs(y - lab.y1) <= 6 or (lab.y0 - 2 <= y <= lab.y1 + 3):  # same row
            g = r.x0 - lab.x1 if r.x0 >= lab.x1 - 3 else lab.x0 - r.x1 if r.x1 <= lab.x0 + 3 else None
            if g is not None and g <= 60:
                cands.append((max(g, 0) + 2, "line", r, _above_line(pi, r, kind)))
    if not cands and (text.rstrip().endswith((":", "：")) or text.lstrip().startswith(":")):
        rtl = _is_rtl_text(text)
        w = 150 if kind == "signature" else 90
        h = min(36.0, pi.space_above(0, pi.rect.width, lab.y1, 36)) if kind == "signature" else lab.height + 2
        x0 = lab.x0 - 6 - w if rtl else lab.x1 + 6
        r = pdfdoc.Rect(x0, lab.y1 - h, x0 + w, lab.y1 + 1)
        if pi.rect.contains(r) and pi.empty(r) and h >= 8:
            cands.append((150, "blank", r, r))
    return cands


def _above_line(pi: PageInfo, rule, kind: str) -> "pdfdoc.Rect":
    if kind == "date":
        return pdfdoc.Rect(rule.x0, rule.y0 - 14, min(rule.x1, rule.x0 + 160), rule.y0)
    w = min(rule.width, 220)
    x0 = rule.x1 - w if pi.rtl else rule.x0
    h = max(16.0, min(46.0, pi.space_above(x0, x0 + w, rule.y0, 46) - 1))
    return pdfdoc.Rect(x0, rule.y0 - h, x0 + w, rule.y0 - 0.5)


def _inset(r, kind):
    if r.height >= 12 and r.width >= 30:
        return pdfdoc.Rect(r.x0 + 2, r.y0 + 2, r.x1 - 2, r.y1 - 2)
    return r


def find_spots(pi: PageInfo, kind: str, used: list) -> list[dict]:
    test = is_date_word if kind == "date" else is_sig_word
    found = []
    for lab, text, grp in _labels(pi, test):
        cs = sorted(_candidates(pi, lab, text, grp, kind), key=lambda c: c[0])
        for score, ttype, target, rect in cs:
            if any(target.intersects(u) and _vover(target, u) > 2 and _hover(target, u) > 2 for u in used):
                continue
            used.append(target)
            found.append({"rect": _inset(rect, kind) if ttype == "box" else rect, "label": text, "target": ttype,
                          "label_rect": lab, "score": score})
            break
    return found


def _spot(page_no: int, r, kind: str, **extra) -> dict:
    return {"page": page_no, "x": round(r.x0, 2), "y": round(r.y0, 2), "width": round(r.width, 2),
            "height": round(r.height, 2), "kind": kind, **extra}


def _widget_kind(w) -> str | None:
    label = getattr(w, "field_label", None)
    if is_id_label(f"{w.field_name or ''} {label or ''}"):
        return None
    if pdf.is_date_field(w.field_name, label):
        return "date"
    if w.field_type == pdfdoc.WIDGET_SIGNATURE:
        return "signature"
    if w.field_type == pdfdoc.WIDGET_TEXT and (is_sig_word(f"{w.field_name or ''} {label or ''}") or any(
            is_sig_word(t) for t in re.split(r"[\s_\-.]+|(?<=[a-z])(?=[A-Z])", f"{w.field_name or ''} {label or ''}")
            if t)) and not (w.field_value or "").strip():
        return "signature"
    return None


def _sort_spots(sigs: list) -> None:
    # This is also the order consumed by --spots: role, then page and geometry.
    for spot in sigs:
        spot["label"] = logical_label(spot.get("label", ""))
        spot["role_hint"] = role_hint(spot["label"])
    sigs.sort(key=lambda s: ({"signer?": 0, "unknown": 1, "official?": 2}[s["role_hint"]],
                             s["page"], round(s["_rect"].y0 / 4), s["_rect"].x0))


def detect(data: bytes) -> dict:
    """All signature and date spots: {"signature": [...], "date": [...], "method": ..., "has_text": bool}."""
    sigs, dates = [], []
    with pdfdoc.Document.open(data) as doc:
        for p in doc:
            for w in p.widgets() or []:
                k = _widget_kind(w)
                if k:
                    (sigs if k == "signature" else dates).append(
                        {"field_name": w.field_name, "kind": k, "source": "form field", "page": p.number + 1,
                         "label": getattr(w, "field_label", None) or w.field_name,
                         "_rect": pdfdoc.Rect(w.rect)})
        from_fields = bool(sigs)
        has_text = False
        for p in doc:
            pi = PageInfo(p)
            has_text = has_text or bool(pi.text_words)
            used: list = [s["_rect"] for s in sigs if s["page"] == p.number + 1]
            if not from_fields:
                for s in find_spots(pi, "signature", used):
                    sigs.append(_spot(p.number + 1, s["rect"], "signature", source="label", label=s["label"],
                                      target=s["target"]) | {"_rect": s["rect"]})
            if not any(d.get("field_name") for d in dates):
                for s in find_spots(pi, "date", used):
                    dates.append(_spot(p.number + 1, s["rect"], "date", source="label", label=s["label"],
                                       target=s["target"]) | {"_rect": s["rect"]})
        if from_fields:
            _sort_spots(sigs)
            return {"signature": sigs, "date": dates, "method": "form field", "has_text": True}
    _sort_spots(sigs)
    return {"signature": sigs, "date": dates, "method": "label" if sigs else "none", "has_text": has_text}


def id_areas(page) -> list:
    """Protect ID boxes and the writing area above ID rules, including AcroForm labels."""
    return [pdfdoc.Rect(r.x0, r.y0 - 30, r.x1, r.y1 + 2) if r.height <= 2 else r
            for r in PageInfo(page).id_targets]


def safe_placements(doc, placements: list[dict]) -> list[dict]:
    areas = {p.number: id_areas(p) for p in doc}
    out = []
    for pl in placements:
        if is_id_label(pl.get("field_name", "")):
            continue
        idx, rect = pdf.resolve_rect(doc, pl)
        if not any(rect.intersects(r) for r in areas[idx]):
            out.append(pl)
    return out


def _clean(s: dict) -> dict:
    return {k: v for k, v in s.items() if not k.startswith("_")}


def _select(sigs: list, spots) -> list:
    if spots in (None, "all", "", []):
        return sigs
    if spots == "first":
        return sigs[:1]
    if spots == "last":
        return sigs[-1:]
    if isinstance(spots, str) and "," in spots:
        spots = spots.split(",")
    if isinstance(spots, (int, str)):
        spots = [spots]
    out = []
    for n in spots:
        try:
            n = int(n)
        except (TypeError, ValueError) as e:
            raise ValueError(f"spots must be 'all', 'first', 'last' or a list of spot numbers, got {spots!r}") from e
        if not 1 <= n <= len(sigs):
            raise ValueError(f"spot {n} out of range: {len(sigs)} signature spot(s) were detected")
        out.append(sigs[n - 1])
    return out


def _nearest_dates(sig_rects: list[tuple[int, "pdfdoc.Rect"]], dates: list) -> list:
    chosen = []
    for page, r in sig_rects:
        best = None
        for d in dates:
            if d["page"] != page or d in chosen:
                continue
            dr = d["_rect"]
            dist = abs((dr.y0 + dr.y1) / 2 - (r.y0 + r.y1) / 2) * 2 + abs((dr.x0 + dr.x1) / 2 - (r.x0 + r.x1) / 2) * 0.3
            if abs((dr.y0 + dr.y1) / 2 - (r.y0 + r.y1) / 2) <= 160 and (best is None or dist < best[0]):
                best = (dist, d)
        if best:
            chosen.append(best[1])
    return chosen


def plan(data: bytes, placements: list[dict] | None, add_date: bool = False, spots=None) -> tuple[list[dict], dict]:
    """Final placements plus info {"method", "guess", "note", "detected_signature_spots", ...}."""
    placements = [dict(p) for p in (placements or [])]
    info: dict = {"guess": False}
    det = None
    if not placements:
        det = detect(data)
        sigs = det["signature"]
        info["detected_signature_spots"] = len(sigs)
        if sigs:
            chosen = _select(sigs, spots)
            placements = [_clean(s) for s in chosen]
            info["method"] = det["method"]
            info["note"] = (f"Found {len(sigs)} signature spot(s) by "
                            + ("form field" if det["method"] == "form field" else "label ('" + "', '".join(
                                s.get("label", "") for s in sigs[:5]) + "')")
                            + (f"; signing {len(chosen)} of them" if len(chosen) != len(sigs) else "") + ".")
        else:
            _select(sigs, spots)
            with pdfdoc.Document.open(data) as doc:
                p = doc[-1]
                w, h = p.rect.width, p.rect.height
                placements = [{"page": doc.page_count, "x": round(w - 72 - 180, 2), "y": round(h - 72 - 60, 2),
                               "width": 180, "height": 60, "kind": "signature", "source": "guess"}]
            info.update(method="guess", guess=True, note=(
                ("The PDF has no text layer (scanned?), so " if not det["has_text"] else
                 "No signature label, box or field was found, so ")
                + "the signature was placed at the bottom right of the last page. This is a GUESS: show the preview "
                  "to the user and pass explicit placements if it is wrong."))
    else:
        info.update(method="explicit", note="Using the placements you gave.")
    if add_date and not any(p.get("kind") == "date" for p in placements):
        det = det or detect(data)
        dates = det["date"]
        with pdfdoc.Document.open(data) as doc:
            rects = []
            for p in placements:
                if p.get("kind", "signature") == "date" or p.get("fill_document_date") is False:
                    continue
                idx, r = pdf.resolve_rect(doc, p)
                rects.append((idx + 1, r))
        add = _nearest_dates(rects, dates)
        for d in add:
            placements.append(_clean(d) | {"auto_date": True})
        info["date_spots"] = len(add)
        if add:
            info["note"] += f" Date goes in {len(add)} detected date spot(s)."
    with pdfdoc.Document.open(data) as doc:
        placements = safe_placements(doc, placements)
    return placements, info


# ------------------------------------------------------------------ previews
_COLORS = {"signature": (0.12, 0.37, 1.0), "initials": (0.12, 0.37, 1.0), "date": (0.9, 0.45, 0.0)}


def boxes(doc, placements: list[dict]) -> list[dict]:
    """Placements as page-relative boxes (0..1) for the signing pages."""
    out = []
    for p in placements:
        idx, r = pdf.resolve_rect(doc, p)
        pw, ph = doc[idx].display_size
        r = doc[idx].rect_to_display(r)  # the signing page shows pages as displayed (rotation applied)
        out.append({"page": idx + 1, "kind": p.get("kind", "signature"), "left": r.x0 / pw, "top": r.y0 / ph,
                    "width": r.width / pw, "height": r.height / ph})
        if p.get("date_format"):  # lets the page show the same date string the PDF will get
            out[-1]["date_format"] = str(p["date_format"])[:40]
    return out


def _label(kind: str) -> str:
    return {"date": "Date", "initials": "Initials"}.get(kind, "Sign here")


def preview_pngs(data: bytes, placements: list[dict], out_dir: Path, stem: str, width_px: int = 1000) -> list[str]:
    """One PNG per page that has a spot, with the spots highlighted. Returns absolute paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with pdfdoc.Document.open(data) as doc:
        by_page: dict[int, list] = {}
        for i, p in enumerate(placements):
            idx, r = pdf.resolve_rect(doc, p)
            by_page.setdefault(idx, []).append((i + 1, p.get("kind", "signature"), r))
        for idx in sorted(by_page):
            page = doc[idx]
            for n, kind, r in by_page[idx]:
                c = _COLORS.get(kind, _COLORS["signature"])
                page.draw_rect(r, color=c, fill=c, fill_opacity=0.18, width=1.6, dashes=(3, 2))
                tag = f"{n}. {_label(kind)}"
                fs = 7.5
                tw = pdfdoc.text_length(tag, fs)
                ty = r.y0 - 2 if r.y0 > 12 else r.y1 + fs + 1
                bg = pdfdoc.Rect(r.x0, ty - fs, r.x0 + tw + 4, ty + 2)
                page.draw_rect(bg, color=None, fill=c, width=0)
                page.insert_text((r.x0 + 2, ty), tag, fontsize=fs, color=(1, 1, 1))
        marked = doc.tobytes()
        for idx in sorted(by_page):
            zoom = max(0.5, min(3.0, width_px / doc[idx].display_size[0]))
            pth = out_dir / f"{stem} - preview page {idx + 1}.png"
            pth.write_bytes(pdfdoc.render_png(marked, idx, zoom))
            paths.append(str(pth.resolve()))
    return paths


def signed_spots_png(signed: bytes, placements: list[dict], path: Path, width_px: int = 700) -> str | None:
    """A small image of just the signed areas (with some context), stacked if on several pages."""
    try:
        src = pdfdoc.Document.open(signed)
    except Exception:  # noqa: BLE001
        return None
    with src:
        clips: dict[int, pdfdoc.Rect] = {}
        for p in placements:
            try:
                idx, r = pdf.resolve_rect(src, p) if not p.get("field_name") else _field_rect(p)
            except Exception:  # noqa: BLE001 - form fields are gone after stamping; skip
                continue
            clips[idx] = (clips[idx] | r) if idx in clips else pdfdoc.Rect(r)
        if not clips:
            return None
        parts = []
        for idx, c in sorted(clips.items()):
            pg = src[idx]
            c = pg.rect_to_display(pdfdoc.Rect(c.x0 - 30, c.y0 - 24, c.x1 + 30, c.y1 + 24) & pg.rect)
            parts.append((idx, c))
    W = max(c.width for _, c in parts)
    H = sum(c.height for _, c in parts) + 6 * (len(parts) - 1)
    zoom = max(0.5, min(4.0, width_px / W))
    from PIL import Image
    sheet = Image.new("RGB", (max(1, round(W * zoom)), max(1, round(H * zoom))), "white")
    y = 0.0
    for idx, c in parts:
        img = pdfdoc.render_image(signed, idx, zoom)
        img = img.crop((round(c.x0 * zoom), round(c.y0 * zoom), round(c.x1 * zoom), round(c.y1 * zoom)))
        sheet.paste(img, (0, round(y * zoom)))
        y += c.height + 6
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(path), "PNG")
    return str(path.resolve())


def _field_rect(p: dict):
    if "_page_idx" in p and "_rect" in p:
        return p["_page_idx"], pdfdoc.Rect(p["_rect"])
    raise KeyError("field")


def with_rects(data: bytes, placements: list[dict]) -> list[dict]:
    """Copy of placements with resolved page/rect (so field placements can be found after stamping)."""
    out = []
    with pdfdoc.Document.open(data) as doc:
        for p in placements:
            q = dict(p)
            try:
                idx, r = pdf.resolve_rect(doc, p)
                q.update(page=idx + 1, x=r.x0, y=r.y0, width=r.width, height=r.height)
                q.pop("field_name", None)
            except Exception:  # noqa: BLE001
                pass
            out.append(q)
    return out


def completed_next(output_path: str, preview_png: str | None) -> str:
    return ("Signed. Send the signed PDF back to the signer in this chat right away, without waiting to be asked: "
            f"attach the file {output_path}"
            + (f" and show this small preview of the signed spots: {preview_png}" if preview_png else "")
            + ". Do not just mention the path; attach the actual file.")


def finish(result: dict, original: bytes | None, placements: list[dict] | None, cache_dir: Path) -> dict:
    """Add signed_pdf_path / signed_preview_png_path / next to a completed status result."""
    if result.get("status") != "completed" or not result.get("output_path"):
        return result
    out = Path(result["output_path"])
    if not out.is_file():
        return result
    png = cache_dir / "signed spots preview.png"
    prev = str(png.resolve()) if png.is_file() else None
    if prev is None and placements:
        pls = with_rects(original, placements) if original else placements
        try:
            prev = signed_spots_png(out.read_bytes(), [p for p in pls if "x" in p], png)
        except Exception:  # noqa: BLE001 - preview is a nice-to-have
            prev = None
    result.update(signed_pdf_path=str(out.resolve()), signed_preview_png_path=prev,
                  next=completed_next(str(out.resolve()), prev))
    return result
