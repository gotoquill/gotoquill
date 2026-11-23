"""No-connection (offline file) mode."""
import base64
import hashlib
import hmac
import json
import re
import zlib

import pytest

from gotoquill import offline, tools
from gotoquill.core import SignError

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def page_data(html: str) -> dict:
    m = re.search(r"const D = (\{.*?\});\n", html)
    return json.loads(m.group(1))


def make_response(d: dict, **over) -> dict:
    r = {"type": "gotoquill-response", "version": 1, "request_id": d["request_id"], "original_sha256": d["original_sha256"],
         "decision": "sign", "signature_png": "data:image/png;base64," + base64.b64encode(PNG).decode(),
         "method": "drawn", "typed_name": "", "signer_name": "Dana Signer", "consent": True,
         "consent_text": d["consent_text"], "client_timestamp": "2020-01-01T00:00:00Z", "user_agent": "test"}
    r.update(over)
    msg = offline.proof_message(r["request_id"], r["original_sha256"], hashlib.sha256(PNG).hexdigest(), r["method"],
                                r["typed_name"], r["signer_name"], r["client_timestamp"])
    r.setdefault("proof", hmac.new(bytes.fromhex(d["key"]), msg.encode(), hashlib.sha256).hexdigest())
    return r


@pytest.fixture()
def req(env, pdf_file):
    r = tools.request_signature(str(pdf_file), delivery="file", signer_name="Dana Signer")
    html = open(r["html_path"], encoding="utf-8").read()
    return r, html, page_data(html)


def test_html_is_self_contained(req, pdf_file):
    r, html, d = req
    assert r["html_path"].endswith("Contract - sign.html") and "_" not in r["html_path"].rsplit("/", 1)[1]
    assert d["request_id"] == r["request_id"] and d["original_sha256"] == hashlib.sha256(pdf_file.read_bytes()).hexdigest()
    assert "data:image/png;base64," in html and d["boxes"] and d["response_name"] == "Contract - signature"
    # Privacy links are deliberate navigation, not external resources or network dependencies.
    external = re.findall(r"""(?:src|href)\s*=\s*["'](https?://[^"']+)""", html)
    assert set(external) == {"https://gotoquill.com/privacy/", "https://gotoquill.com/privacy/he/"}
    assert "fetch(" not in html and "XMLHttpRequest" not in html and "connect-src 'none'" in html


def test_apply_file_and_code_one_time(req, tmp_path):
    r, _, d = req
    resp = make_response(d)
    f = tmp_path / "Contract - signature.gotoquill"
    f.write_text(json.dumps(resp))
    out = tools.call("apply_signature_response", {"request_id": r["request_id"], "response_path": str(f)})
    assert out["status"] == "completed"
    audit = json.load(open(out["audit_path"]))
    assert audit["delivery"] == "file via chat" and audit["signer_name"] == "Dana Signer"
    assert open(out["output_path"], "rb").read().startswith(b"%PDF")
    again = tools.call("apply_signature_response", {"request_id": r["request_id"], "response_path": str(f)})
    assert "only once" in again["error"]
    assert tools.get_signature_status(r["request_id"])["status"] == "completed"


def test_compact_code(req):
    r, _, d = req
    z = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = z.compress(json.dumps(make_response(d)).encode()) + z.flush()
    code = "GOTOQUILL1Z." + base64.urlsafe_b64encode(raw).decode().rstrip("=")
    wrapped = "here you go:\n" + "\n".join(code[i:i + 60] for i in range(0, len(code), 60))
    out = offline.apply_signature_response(r["request_id"], response_text=wrapped)
    assert out["status"] == "completed"


def test_rejects_tampering_and_other_requests(req, pdf_file):
    r, _, d = req
    with pytest.raises(SignError, match="proof"):
        offline.apply_signature_response(r["request_id"], response_text=json.dumps(make_response(d, signer_name="Mallory", proof="00")))
    good = make_response(d)
    bad = dict(good, signer_name="Mallory")  # changed after signing
    with pytest.raises(SignError, match="proof"):
        offline.apply_signature_response(r["request_id"], response_text=json.dumps(bad))
    with pytest.raises(SignError, match="hash"):
        offline.apply_signature_response(r["request_id"], response_text=json.dumps(dict(good, original_sha256="0" * 64)))
    r2 = tools.request_signature(str(pdf_file), delivery="file", html_path=str(pdf_file.parent / "Other - sign.html"))
    with pytest.raises(SignError, match="different request"):
        offline.apply_signature_response(r2["request_id"], response_text=json.dumps(good))
    # replay with the second request's id but the first key's proof fails
    with pytest.raises(SignError, match="proof"):
        offline.apply_signature_response(r2["request_id"], response_text=json.dumps(dict(good, request_id=r2["request_id"])))


def test_expiry_cancel_and_restart(req, pdf_file):
    r, _, d = req
    st = offline._load(r["request_id"])
    st["expires_at"] = "2000-01-01T00:00:00Z"
    offline._store(st)
    with pytest.raises(SignError, match="expired"):
        offline.apply_signature_response(r["request_id"], response_text=json.dumps(make_response(d)))
    r2 = tools.request_signature(str(pdf_file), delivery="file", html_path=str(pdf_file.parent / "B - sign.html"))
    from gotoquill import local
    local.reset_signer()  # simulated restart: state is on disk in the config dir
    assert tools.get_signature_status(r2["request_id"])["status"] == "pending"
    assert tools.cancel_request(r2["request_id"])["status"] == "cancelled"


def test_done_screen_copy_primary_and_share(req):
    _, html, _ = req
    done = html[html.index('id="done"'):html.index("</main>")]
    assert done.count('class="primary') == 1
    assert 'id="copy"' in done and "Copy response code" in done and 'class="primary big"' in done
    assert 'id="send"' in done and "Share reply file" in done
    assert "Paste this back into the chat" in done
    assert "paste it as a message" in done or "paste it into the chat" in done or "Paste it into the chat" in html
    assert 'id="code"' in done and 'id="share"' not in html
    assert "function notifyHost" in html and "postMessage" in html and "navigator.share" in html
    trouble = done[done.index('<details id="trouble"'):done.index("</details>")]
    assert "Other ways to send it back" in trouble and 'id="download"' in trouble
