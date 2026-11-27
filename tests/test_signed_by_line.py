"""Optional 'Signed by {name} · {date}' line under each signature (off by default)."""
import io
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from gotoquill import pdf, tools
from tests.test_file_mode import PNG, make_response, page_data

ROOT = Path(__file__).resolve().parents[1]


def _text(b: bytes) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(b)).pages)


@pytest.fixture()
def req(env, pdf_file):
    r = tools.request_signature(str(pdf_file), delivery="file", signer_name="Dana Signer")
    return r, page_data(open(r["html_path"], encoding="utf-8").read())


def _apply(r, d, tmp_path, **over):
    f = tmp_path / "resp.gotoquill"
    f.write_text(json.dumps(make_response(d, **over)))
    out = tools.call("apply_signature_response", {"request_id": r["request_id"], "response_path": str(f)})
    assert out["status"] == "completed"
    return Path(out["output_path"]).read_bytes()


def test_default_off_adds_no_line(req, tmp_path):
    r, d = req
    assert "Signed by" not in _text(_apply(r, d, tmp_path))


def test_on_adds_line_under_signature(req, tmp_path):
    r, d = req
    t = _text(_apply(r, d, tmp_path, signed_by_line=True))
    assert "Signed by Dana Signer" in t and "\u00b7" in t


def test_truthy_strings_do_not_enable(req, tmp_path):
    r, d = req
    assert "Signed by" not in _text(_apply(r, d, tmp_path, signed_by_line="yes"))


def test_stamp_line_sits_below_spot(pdf_file):
    from datetime import datetime, timezone
    data = pdf_file.read_bytes()
    pl = [{"page": 1, "x": 100, "y": 300, "width": 120, "height": 40, "kind": "signature"}]
    off = pdf.stamp(data, pl, PNG, datetime(2026, 10, 26, 12, tzinfo=timezone.utc), "Dana Signer", "req_x")
    on = pdf.stamp(data, pl, PNG, datetime(2026, 10, 26, 12, tzinfo=timezone.utc), "Dana Signer", "req_x", signed_by_line=True)
    assert "Signed by" not in _text(off) and "Signed by Dana Signer" in _text(on)
    assert pdf.signed_by_text("  Dana   Signer ", "26 Oct 2026") == "Signed by Dana Signer \u00b7 26 Oct 2026"


@pytest.mark.parametrize("html,js", [("web/index.html", "web/sign.js"), ("gotoquill/static/sign.html", None),
                                     ("gotoquill/static/offline.html", None)])
def test_pages_have_checkbox_off_and_send_choice(html, js):
    h = (ROOT / html).read_text(encoding="utf-8")
    s = (ROOT / (js or html)).read_text(encoding="utf-8")
    assert '<input type="checkbox" id="signedBy">' in h and 'id="signedBy" checked' not in h
    assert "under my signature" in h and "signed_by_line: sbChecked()" in s


# --- the checkbox label shows exactly the date string the PDF will stamp ---------------------------

import datetime as _dt
import json as _json
import shutil as _shutil
import subprocess as _sp
from pathlib import Path as _Path

import pytest as _pytest

from gotoquill import pdf as _pdf

_ROOT = _Path(__file__).resolve().parents[1]
_COPIES = [_ROOT / "gotoquill/static/sign.html", _ROOT / "gotoquill/static/offline.html"]


def _sbdate_block(path):
    s = path.read_text()
    return s[s.index("// sbdate:start"):s.index("// sbdate:end")]


def test_label_date_helpers_identical_in_all_copies():
    blocks = {_sbdate_block(p) for p in _COPIES}
    assert len(blocks) == 1


@_pytest.mark.skipif(not _shutil.which("node"), reason="node not installed")
def test_label_date_equals_stamped_date():
    when = _dt.datetime(2026, 3, 7, 9, 5)
    cases = [(f, loc) for f in (None, "auto", "locale", "DD/MM/YYYY", "MMMM DD, YYYY", "MMM DD YY HH:mm", "%d %b %Y", "%A %B %d")
             for loc in ("en-US", "en-GB", "de-DE", "sv-SE", "fr-CA", "ja", "pt_BR", "")]
    js = _sbdate_block(_COPIES[0]) + (
        "const d = new Date(2026, 2, 7, 9, 5);\n"
        f"const cases = {_json.dumps(cases)};\n"
        "console.log(JSON.stringify(cases.map(([f, l]) => sbDate(d, sbStrf(f, l)))));\n")
    got = _json.loads(_sp.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    want = [when.strftime(_pdf.to_strftime(f, loc)) for f, loc in cases]
    assert got == want


def test_boxes_carry_date_format():
    from gotoquill import placement
    import inspect
    assert '"date_format"' in inspect.getsource(placement.boxes)
