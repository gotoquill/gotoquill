"""Auto-placement: labels (LTR/RTL), boxes/lines, form fields, multiple spots, scanned fallback, previews."""
import os
from pathlib import Path

import pytest

from gotoquill import offline, placement as pl
from gotoquill.pdfdoc import Rect
from pdfmake import Doc

HEB = "/usr/share/fonts/truetype/sand-box/google/IBM Plex Sans Hebrew/IBMPlexSansHebrew-Regular.ttf"


def _box(page, r):  # draw a box as 4 separate lines (like many real forms do)
    page.box(r, width=0.8)


def _inside(p, r, tol=2):
    r = Rect(r)
    return p["x"] >= r.x0 - tol and p["x"] + p["width"] <= r.x1 + tol and p["y"] >= r.y0 - tol and p["y"] + p["height"] <= r.y1 + tol


def _bytes(doc):
    b = doc.tobytes(); doc.close(); return b


@pytest.mark.parametrize("w,ok", [("Signature", True), ("sign:", True), ("Unterschrift", True), ("Firma", True),
                                  ("חתימת", True), ("תמיתח", True), ("erutangiS", True), ("significant", False),
                                  ("signal", False), ("Date", False)])
def test_sig_words(w, ok):
    assert pl.is_sig_word(w) == ok


@pytest.mark.skipif(not os.path.exists(HEB), reason="no Hebrew font")
def test_rtl_label_with_box_beside_it_on_the_left():
    doc = Doc(); page = doc.new_page(width=595, height=842)
    page.insert_text((60, 100), "טופס בקשה", fontfile=HEB, fontsize=14)
    page.insert_text((170, 735), "חתימת המבוטח", fontfile=HEB, fontsize=10)   # label right of the box
    page.insert_text((545, 735), "תאריך", fontfile=HEB, fontsize=10)
    _box(page, (31, 712, 143, 740)); _box(page, (469, 712, 541, 740))
    data = _bytes(doc)
    ps, info = pl.plan(data, None, add_date=True)
    sig = [p for p in ps if p["kind"] == "signature"]; dates = [p for p in ps if p["kind"] == "date"]
    assert len(sig) == 1 and _inside(sig[0], (31, 712, 143, 740)) and not info["guess"]
    assert len(dates) == 1 and _inside(dates[0], (469, 712, 541, 740))


def test_ltr_label_line_above_and_multiple_spots_selection():
    doc = Doc(); page = doc.new_page()
    for x in (60, 330):
        page.draw_line((x, 700), (x + 180, 700))
        page.insert_text((x, 714), "Signature", fontsize=10)
    page.insert_text((60, 400), "Signature: ____________________", fontsize=10)
    data = _bytes(doc)
    ps, info = pl.plan(data, None)
    assert len(ps) == 3 and info["detected_signature_spots"] == 3
    assert all(p["source"] == "label" for p in ps)
    line = [p for p in ps if p["y"] > 600]
    assert all(p["y"] + p["height"] <= 701 and p["y"] > 650 for p in line)
    assert len(pl.plan(data, None, spots="first")[0]) == 1
    assert len(pl.plan(data, None, spots=[1, 3])[0]) == 2
    with pytest.raises(ValueError):
        pl.plan(data, None, spots=[9])


def test_acroform_signature_and_date_fields():
    doc = Doc(); page = doc.new_page()
    for name, r in (("ClientSignature", (72, 600, 272, 640)), ("SignDate", (350, 610, 470, 630))):
        page.text_field(name, r)
    data = _bytes(doc)
    ps, info = pl.plan(data, None, add_date=True)
    assert [p.get("field_name") for p in ps if p["kind"] == "signature"] == ["ClientSignature"]
    assert any(p["kind"] == "date" for p in ps)


def test_scanned_pdf_falls_back_with_guess_note():
    doc = Doc(); doc.new_page(); doc.new_page()
    ps, info = pl.plan(_bytes(doc), None)
    assert info["guess"] and "guess" in info["note"].lower() and ps[0]["page"] == 2 and ps[0]["source"] == "guess"


def test_preview_and_completed_next(tmp_path):
    doc = Doc(); page = doc.new_page()
    page.draw_line((60, 700), (240, 700)); page.insert_text((60, 714), "Signature", fontsize=10)
    data = _bytes(doc); src = tmp_path / "my_form.pdf"; src.write_bytes(data)
    r = offline.create_file_request(pdf_path=str(src), html_path=str(tmp_path / "s.html"))
    assert r["placements"] and Path(r["preview_png_path"]).is_file() and "preview" in r["next"].lower()
    assert Path(r["output_path"]).name == "my form - signed.pdf"
    res = pl.finish({"status": "completed", "output_path": str(src)}, data, r["placements"], tmp_path)
    assert res["signed_pdf_path"] == str(src) and Path(res["signed_preview_png_path"]).is_file()
    assert "without waiting to be asked" in res["next"] and str(src) in res["next"]
