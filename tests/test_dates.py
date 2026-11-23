"""Signing date: proof line in the signer's time zone, filling the document's own date spot."""
from datetime import datetime, timezone

from gotoquill import pdf
from pdfmake import Doc, Opened, sig_png

AT = datetime(2026, 10, 25, 23, 20, tzinfo=timezone.utc)
NY = {"timezone": "America/New_York", "utc_offset_minutes": -240, "locale": "en-GB"}


def _stamp(data, pls, signer=None):
    return Opened(pdf.stamp(data, pls, sig_png(), AT, "X", "rid", signer))


def test_proof_line_uses_signer_timezone(sample_pdf):
    with _stamp(sample_pdf, [{"field_name": "ContractorSignature", "add_date": True}], NY) as d:
        assert "Signed 25 Oct 2026, 19:20 (America/New_York)" in d[0].get_text()


def test_offset_fallback_and_utc_default():
    assert pdf.signer_zone({"timezone": "Not/AZone", "utc_offset_minutes": 180})[1] == "UTC+03:00"
    assert pdf.signer_zone({"utc_offset_minutes": -330})[1] == "UTC-05:30"
    assert pdf.signer_zone(None)[1] == "UTC"


def test_date_formats():
    assert pdf.to_strftime(None, None) == "%d %b %Y"
    assert pdf.to_strftime(None, "en-US") == "%m/%d/%Y"
    assert pdf.to_strftime(None, "he-IL") == "%d/%m/%Y"
    assert pdf.to_strftime(None, "sv-SE") == "%Y-%m-%d"
    assert pdf.to_strftime("DD/MM/YYYY") == "%d/%m/%Y"
    assert pdf.to_strftime("%Y.%m.%d") == "%Y.%m.%d"


def test_label_detection_writes_date_on_line_above_date_label(sample_pdf):
    with _stamp(sample_pdf, [{"field_name": "ContractorSignature", "add_date": True}], NY) as d:
        p = d[0]
        hit = p.search_for("25/10/2026")
        label = p.search_for("Date")[-1]
        assert len(hit) == 1 and label.x0 == 340
        h = hit[0]
        assert h.x0 >= 340 and h.y1 <= 641 and h.y0 > 620  # sits on the rule at y=640, above the label
        assert not h.intersects(label)
        proof = p.search_for("Signed 25 Oct 2026")[0]
        assert not proof.intersects(h) and not proof.intersects(p.search_for("Contractor signature")[0])


def test_proof_line_off(sample_pdf):
    with _stamp(sample_pdf, [{"field_name": "ContractorSignature", "add_date": True, "proof_line": False}], NY) as d:
        t = d[0].get_text()
        assert "Signed " not in t and "25/10/2026" in t


def test_explicit_date_placement_wins(sample_pdf):
    pls = [{"field_name": "ContractorSignature", "add_date": True},
           {"kind": "date", "page": 1, "x": 400, "y": 700, "width": 100, "height": 14, "date_format": "YYYY-MM-DD"}]
    with _stamp(sample_pdf, pls, NY) as d:
        t = d[0].get_text()
        assert "2026-10-25" in t and "25/10/2026" not in t


def test_no_date_box(tmp_path):
    doc = Doc(); p = doc.new_page()
    p.insert_text((72, 100), "Just some text, no date spot here.")
    data = doc.tobytes()
    with _stamp(data, [{"page": 1, "x": 72, "y": 600, "width": 180, "height": 60, "add_date": True}], NY) as d:
        t = d[0].get_text()
        assert "Signed 25 Oct 2026, 19:20 (America/New_York)" in t and "25/10/2026" not in t


def test_date_form_field_filled_incl_hebrew():
    for name in ("SignDate", "תאריך"):
        doc = Doc(); p = doc.new_page()
        p.text_field(name, (340, 600, 500, 620))
        data = doc.tobytes()
        with _stamp(data, [{"page": 1, "x": 72, "y": 580, "width": 180, "height": 60, "add_date": True}],
                    {**NY, "locale": "en-US"}) as d:
            vals = {x.field_name: x.field_value for x in d[0].widgets()}
            assert name not in vals
            assert "10/25/2026" in d[0].get_text()
    assert not pdf.is_date_field("candidate_update")


def test_hebrew_rtl_label_same_row():
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    doc = Doc(); p = doc.new_page()
    p.insert_text((480, 650), "\u05ea\u05d0\u05e8\u05d9\u05da:", fontfile=font, fontsize=11)
    p.draw_line((330, 652), (470, 652))
    data = doc.tobytes()
    with _stamp(data, [{"page": 1, "x": 340, "y": 580, "width": 180, "height": 60, "add_date": True,
                        "proof_line": False}], {**NY, "locale": "he-IL"}) as d:
        h = d[0].search_for("25/10/2026")
        assert h and 330 <= h[0].x0 and h[0].x1 <= 470 and h[0].y1 <= 653


def test_signer_context_sanitized():
    from gotoquill.offline import signer_context
    c = signer_context({"signer_timezone": "America/New_York", "signer_utc_offset": -240, "signer_locale": "he-IL"})
    assert c == {"timezone": "America/New_York", "utc_offset_minutes": -240, "locale": "he-IL"}
    bad = signer_context({"signer_timezone": "<script>", "signer_utc_offset": 99999, "signer_locale": "x y"})
    assert bad == {"timezone": None, "utc_offset_minutes": None, "locale": None}
