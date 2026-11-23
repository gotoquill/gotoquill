"""Sealed-link mode with an in-memory fake relay: we play the browser page in Python (same AES-GCM + HMAC)."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import parse_qs

import pytest
from pdfmake import blank_png, image_count

from gotoquill import offline, relay, sealed, tools

PNG = base64.b64encode(blank_png(60, 20)).decode()


def open_link(url, fake):
    """What web/sign.js does: parse the fragment, fetch + decrypt the request."""
    frag = parse_qs(url.split("#", 1)[1])
    q, a, k = frag["q"][0], frag["a"][0], frag["k"][0]
    key = base64.urlsafe_b64decode(k + "=" * (-len(k) % 4))
    blob = fake.fetch(q)[-1]
    payload = json.loads(relay.unseal(key, blob, relay.aad("request", q)))
    return payload, key, a


def reply(payload, key, reply_topic, fake, decision="sign", tamper=None, rid=None):
    D = payload["data"]
    r = {"type": "gotoquill-response", "version": 1, "request_id": rid or D["request_id"],
         "original_sha256": D["original_sha256"], "client_timestamp": "", "decision": decision}
    if decision == "sign":
        r.update(signature_png="data:image/png;base64," + PNG, method="drawn", typed_name="", signer_name="Dana",
                 consent=True, consent_text=D["consent_text"])
        sig = hashlib.sha256(base64.b64decode(PNG)).hexdigest()
        msg = offline.proof_message(r["request_id"], D["original_sha256"], sig, "drawn", "", "Dana", "")
        r["proof"] = hmac.new(bytes.fromhex(D["key"]), msg.encode(), hashlib.sha256).hexdigest()
    if tamper:
        tamper(r)
    fake.publish(reply_topic, relay.seal(key, json.dumps(r).encode(), relay.aad("reply", reply_topic)))


def test_default_is_sealed_link_and_relay_sees_only_ciphertext(env, pdf_file, fake_relay):
    r = tools.request_signature(str(pdf_file), signer_name="Dana")
    assert r["delivery"] == "sealed link via relay" and r["sign_url"].startswith("https://pages.test/gotoquill/#v=1&q=")
    assert Path(r["qr_png_path"]).read_bytes()[:4] == b"\x89PNG" and r["qr_ascii"]
    payload, key, a = open_link(r["sign_url"], fake_relay)
    assert payload["document_sha256"] == hashlib.sha256(pdf_file.read_bytes()).hexdigest()
    assert base64.b64decode(payload["pdf_base64"]) == pdf_file.read_bytes() and payload["pages"]
    # relay only ever saw ciphertext: no PDF magic, no request id, no name, no base64 of the PDF
    for blobs in fake_relay.topics.values():
        for b in blobs:
            assert b"%PDF" not in b and r["request_id"].encode() not in b and b"Dana" not in b and b"iVBOR" not in b
    assert tools.get_signature_status(r["request_id"])["status"] == "pending"
    reply(payload, key, a, fake_relay)
    st = tools.get_signature_status(r["request_id"], wait_seconds=2)
    assert st["status"] == "completed", st
    audit = json.loads(Path(st["audit_path"]).read_text())
    assert audit["delivery"] == "sealed link via relay" and audit["proof"] == "hmac-sha256 verified"
    assert image_count(st["output_path"]) >= 1
    for b in fake_relay.topics[a]:
        assert b"Dana" not in b and b"iVBOR" not in b
    # one-time: a second reply is ignored, key is forgotten
    reply(payload, key, a, fake_relay)
    assert tools.get_signature_status(r["request_id"])["status"] == "completed"
    assert offline._load(r["request_id"])["sealed"]["key"] is None


def test_forged_and_tampered_replies_rejected(env, pdf_file, fake_relay):
    r = tools.request_signature(str(pdf_file))
    payload, key, a = open_link(r["sign_url"], fake_relay)
    fake_relay.publish(a, b"junk" * 20)                                       # not decryptable
    fake_relay.publish(a, relay.seal(b"\0" * 32, b"{}", relay.aad("reply", a)))  # wrong key
    reply(payload, key, a, fake_relay, tamper=lambda x: x.update(signer_name="Mallory"))  # HMAC breaks
    st = tools.get_signature_status(r["request_id"])
    assert st["status"] == "pending" and "proof" in st["warning"]
    reply(payload, key, a, fake_relay, decision="decline")
    assert tools.get_signature_status(r["request_id"])["status"] == "declined"


def test_reply_for_other_request_and_expiry(env, pdf_file, fake_relay):
    r = tools.request_signature(str(pdf_file))
    payload, key, a = open_link(r["sign_url"], fake_relay)
    reply(payload, key, a, fake_relay, rid="req_0000000000000000")
    assert tools.get_signature_status(r["request_id"])["status"] == "pending"
    with pytest.raises(Exception):
        tools.request_signature(str(pdf_file), expires_in_minutes=181)
    d = offline._load(r["request_id"]); d["expires_at"] = "2000-01-01T00:00:00Z"; offline._store(d)
    assert tools.get_signature_status(r["request_id"])["status"] == "expired"


def test_relay_down_gives_clear_error(env, pdf_file):
    class Down(relay.MemoryRelay):
        def publish(self, *a, **k):
            raise relay.RelayError("offline")
    relay.set_relay(Down())
    out = tools.call("request_signature", {"pdf_path": str(pdf_file)})
    assert out["code"] == 502 and "delivery='file'" in out["error"]


def test_custom_relay_in_link(env, pdf_file, fake_relay):
    fake_relay.base_url = "https://ntfy.example.org"
    r = tools.request_signature(str(pdf_file))
    assert "&r=https%3A%2F%2Fntfy.example.org" in r["sign_url"]


def test_static_page_has_no_external_scripts():
    root = Path(__file__).resolve().parents[1] / "web"
    html = (root / "index.html").read_text()
    js = (root / "sign.js").read_text()
    assert '<script src="sign.js"></script>' in html and "http" not in html.split("<script")[1]
    assert "cdn" not in (html + js).lower() and "AES-GCM" in js and "history.replaceState" in js


def test_url_elicitation_capability_detection():
    from types import SimpleNamespace

    from gotoquill.mcp_server import client_supports_url_elicitation
    mk = lambda caps: SimpleNamespace(client_capabilities=caps)  # noqa: E731
    assert client_supports_url_elicitation(mk({"elicitation": {"url": {}}}))
    assert not client_supports_url_elicitation(mk({"elicitation": {"form": {}}}))
    assert not client_supports_url_elicitation(mk(None))


def test_mcp_default_returns_link(env, pdf_file):
    import anyio
    from mcp.client.session import ClientSession  # noqa: F401
    from gotoquill.mcp_server import build_server

    async def go():
        srv = build_server()
        res = await srv.call_tool("request_signature", {"pdf_path": str(pdf_file)})
        return res
    res = anyio.run(go)
    txt = json.dumps(res, default=str)
    assert "sealed link via relay" in txt and "pages.test" in txt


def _embedded_fragment(html):
    import re
    m = re.search(r'<script>window\.GOTOQUILL_SEALED=("[^"]*");</script>', html)
    assert m, "embedded params missing"
    return json.loads(m.group(1))


@pytest.mark.parametrize("how", [{"delivery": "link-file"}, {"delivery": "link", "as_file": True}])
def test_sealed_file_is_self_contained_and_completes(env, pdf_file, fake_relay, how):
    r = tools.request_signature(str(pdf_file), signer_name="Dana", **how)
    hp = Path(r["html_path"])
    assert hp.name.endswith(" - sign.html") and hp.parent == pdf_file.resolve().parent
    html = hp.read_text()
    assert '<script src=' not in html and "script-src 'self'" not in html and "sha256-" in html
    assert "GOTOQUILL_SEALED" in html and "crypto.subtle" in html  # sign.js inlined
    assert html.index('id="signerPrivacyNotice"') < html.index('<button id="submit"')
    assert 'href="https://gotoquill.com/privacy/"' in html
    assert 'lang="he" dir="rtl"' in html
    frag = _embedded_fragment(html)
    assert frag == r["sign_url"].split("#", 1)[1]
    payload, key, a = open_link("x#" + frag, fake_relay)
    reply(payload, key, a, fake_relay)
    st = tools.get_signature_status(r["request_id"], wait_seconds=2)
    assert st["status"] == "completed", st


def test_sealed_file_csp_hashes_match_inline_scripts(env, pdf_file, fake_relay, tmp_path):
    import re
    hp = tmp_path / "x" / "custom.html"
    r = tools.request_signature(str(pdf_file), delivery="link-file", html_path=str(hp))
    html = hp.read_text()
    assert r["html_path"] == str(hp.resolve())
    csp = re.search(r"script-src ([^;]+);", html).group(1).split()
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(scripts) == 2
    for s in scripts:
        h = "'sha256-" + base64.b64encode(hashlib.sha256(s.encode()).digest()).decode() + "'"
        assert h in csp


def test_plain_link_has_no_html(env, pdf_file, fake_relay):
    r = tools.request_signature(str(pdf_file))
    assert "html_path" not in r


def test_sign_js_has_pure_js_aes_gcm_fallback():
    js = (Path(__file__).resolve().parents[1] / "web" / "sign.js").read_text()
    vend = (Path(__file__).resolve().parents[1] / "web" / "vendor" / "noble-ciphers-aes-gcm.min.js").read_text().strip()
    assert vend in js and "window.nobleGcm" in js and "needs a secure (https) page" not in js
    assert "Tap Download" in js and "open it in Chrome/Safari" in js


def test_vendored_gcm_matches_python_aesgcm(tmp_path):
    import shutil, subprocess, os
    node = shutil.which("node")
    if not node: pytest.skip("no node")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key, iv, aad, pt = os.urandom(32), os.urandom(12), b"gotoquill/sealed/v1|reply|t", b"hello sealed" * 50
    vend = Path(__file__).resolve().parents[1] / "web" / "vendor" / "noble-ciphers-aes-gcm.min.js"
    js = (f"global.window=global;require({str(vend)!r});const h=s=>Uint8Array.from(Buffer.from(s,'hex'));"
          f"const g=window.nobleGcm(h('{key.hex()}'),h('{iv.hex()}'),h('{aad.hex()}'));"
          f"const c=g.encrypt(h('{pt.hex()}'));process.stdout.write(Buffer.from(c).toString('hex')+' '+Buffer.from(window.nobleGcm(h('{key.hex()}'),h('{iv.hex()}'),h('{aad.hex()}')).decrypt(c)).toString('hex'))")
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout.split()
    assert bytes.fromhex(out[0]) == AESGCM(key).encrypt(iv, pt, aad) and bytes.fromhex(out[1]) == pt
