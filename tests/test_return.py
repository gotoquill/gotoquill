import json
import re
import subprocess
import shutil
from pathlib import Path

import httpx
import pytest

from gotoquill.core import SignError
from gotoquill.returnto import normalize

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "web" / "sign.js", ROOT / "gotoquill" / "static" / "offline.html", ROOT / "gotoquill" / "static" / "sign.html"]


def _block(p):
    s = p.read_text(encoding="utf-8")
    m = re.search(r"/\* back-to-chat:start.*?/\* back-to-chat:end \*/", s, re.S)
    assert m, p
    return m.group(0)


@pytest.mark.parametrize("v,out", [
    (None, None), ("", None),
    ("whatsapp", "https://wa.me/?text={text}"),
    ("whatsapp:+1 (555) 010-2000", "https://wa.me/15550102000?text={text}"),
    ("telegram:@my_sign_bot", "https://t.me/my_sign_bot?text={text}"),
    ("sms:+15550102000", "sms:+15550102000?&body={text}"), ("sms", "sms:?&body={text}"),
    ("https://chat.example.com/r?m={text}", "https://chat.example.com/r?m={text}"),
    ("slack://open?team=T1&text={text}", "slack://open?team=T1&text={text}"),
])
def test_normalize_allows(v, out):
    assert normalize(v) == out
    if out:
        assert normalize(out) == out  # idempotent


@pytest.mark.parametrize("v", ["javascript:alert(1)//{text}", "data:text/html,{text}", "file:///etc/passwd",
                               "http://example.com/{text}", "https:///nohost", "vbscript:x", "https://a.com/\"x",
                               "https://a.com/<b>", "https://a.com/a b", "telegram:x", "intent://x", "x" * 600])
def test_normalize_rejects(v):
    with pytest.raises(SignError):
        normalize(v)


def test_js_block_identical_and_schemes_match():
    blocks = {_block(p) for p in FILES}
    assert len(blocks) == 1
    b = blocks.pop()
    from gotoquill.returnto import APP_SCHEMES
    assert all(f"'{s}'" in b for s in APP_SCHEMES) and "javascript" not in b
    assert "You can close this window and go back to the chat. Your signed document will be waiting for you there." in b and "Return to chat" in b
    assert "window.close" not in b and "history.back" not in b and "postMessage" not in b and "Back to chat" not in b
    assert "clipboard" not in b and "backCopy" not in b and "Copy reply" not in b


NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_js_btcurl_and_button(tmp_path):
    b = _block(FILES[0])
    fake = r"""
function El(t){this.tagName=t;this.children=[];this.style={};this.attrs={};this.id='';this.textContent='';}
El.prototype.appendChild=function(c){this.children.push(c);return c};
El.prototype.setAttribute=function(k,v){this.attrs[k]=v;this[k]=v};
El.prototype.addEventListener=function(){};El.prototype.remove=function(){};
El.prototype.querySelector=function(){return null};
const document={createElement:t=>new El(t),getElementById:()=>null,body:new El('body'),execCommand:()=>true};
const navigator={};const window={};
"""
    test = r"""
const out={};
out.wa=btcUrl('https://wa.me/1555?text={text}','I signed X ✅');
out.bad=btcUrl('javascript:alert(1)//{text}','x');
out.none=btcUrl(null,'x');
const box=new El('div');backToChat(box,'https://wa.me/?text={text}','Lease');
function walk(e,f){f(e);(e.children||[]).forEach(c=>walk(c,f))}
const all=[];walk(box,e=>all.push(e));
const a=all.find(e=>e.id==='returnLink');out.tag=a&&a.tagName;out.href=a&&(a.href||a.attrs.href);
out.text=all.map(e=>e.textContent).join('|');
const box2=new El('div');backToChat(box2,null,'Lease');const all2=[];walk(box2,e=>all2.push(e));
out.tag2=(all2.find(e=>e.id==='returnLink')||{tagName:'none'}).tagName;out.text2=all2.map(e=>e.textContent).join('|');const ft=all2.find(e=>e.className==='heroFoot');out.foot=ft&&(ft.href||ft.attrs.href);
console.log(JSON.stringify(out));
"""
    f = tmp_path / "t.js"
    f.write_text(fake + b + test, encoding="utf-8")
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["wa"] == "https://wa.me/1555?text=I%20signed%20X%20%E2%9C%85"
    assert not o["bad"] and not o["none"]
    assert o["tag"].lower() == "a" and o["href"].startswith("https://wa.me/?text=I%20signed%20Lease")
    assert "Return to chat" in o["text"] and "You can close this window and go back to the chat. Your signed document will be waiting for you there." in o["text"]
    assert o["tag2"] == "none" and o["text2"].strip("|") == "You can close this window and go back to the chat. Your signed document will be waiting for you there.|Signed with gotoquill \u2197"
    assert o["foot"] == "https://github.com/gotoquill/gotoquill"


def test_view_posts_ui_message_and_model_context():
    s = FILES[2].read_text(encoding="utf-8")
    assert "'ui/message'" in s and "'ui/update-model-context'" in s and "afterSigned(" in s
    assert "role: 'user'" in s or "role:'user'" in s
    assert "Please send me the signed file" in s and "ui/open-link" in s
    for p in FILES:  # every browser page shows the signed message
        assert "backToChat(" in p.read_text(encoding="utf-8").split("back-to-chat:end")[1]


def test_return_to_in_sealed_payload_file_html_and_page(env, pdf_file):
    from gotoquill import offline, tools
    d, page_data, _, _ = offline.prepare_request(pdf_path=str(pdf_file), return_to="whatsapp:15550102000")
    assert page_data["return_to"] == "https://wa.me/15550102000?text={text}" and d["return_to"]
    r = tools.request_signature(pdf_path=str(pdf_file), delivery="file", return_to="telegram:@my_sign_bot")
    assert "https://t.me/my_sign_bot?text={text}" in Path(r["html_path"]).read_text(encoding="utf-8")
    r = tools.request_signature(pdf_path=str(pdf_file), delivery="page", open_browser=False, return_to="sms")
    assert httpx.get(r["sign_url"] + "/info").json()["return_to"] == "sms:?&body={text}"
    with pytest.raises(SignError):
        tools.request_signature(pdf_path=str(pdf_file), delivery="page", return_to="javascript:x{text}")
    assert "wait_for_signature" in r["wait_tool"]


def test_sealed_link_keeps_return_to_out_of_url(env, pdf_file, monkeypatch):
    from gotoquill import offline
    d, page_data, _, _ = offline.prepare_request(pdf_path=str(pdf_file), return_to="whatsapp")
    assert page_data["return_to"].startswith("https://wa.me/")
    src = (ROOT / "gotoquill" / "sealed.py").read_text(encoding="utf-8")
    assert "return_to" not in src  # never put in the link itself; it rides inside the encrypted page_data


def test_wait_tools_python_and_mcp(env, pdf_file):
    import time

    import anyio

    from gotoquill import tools
    from gotoquill.mcp_server import build_server
    from tests.test_flow import _mcp_call, sign_body
    r = tools.request_signature(pdf_path=str(pdf_file), delivery="page", open_browser=False, wait_seconds=0.5)
    assert r["final_status"]["status"] == "pending" and "same turn" in r["next"]
    w = tools.wait_for_signature(r["request_id"], 0.2)
    assert w["status"] == "pending" and "wait_for_signature" in w["next"]

    srv = build_server()
    call = _mcp_call(srv)

    async def flow():
        st = await call("wait_for_signature", {"request_id": r["request_id"], "wait_seconds": 0.3})
        assert st["status"] == "pending" and "wait_for_signature" in st["next"]
        t0 = time.monotonic()
        with anyio.move_on_after(0.5):  # the server is not blocked: other calls run during a wait
            async with anyio.create_task_group() as tg:
                tg.start_soon(call, "wait_for_signature", {"request_id": r["request_id"], "wait_seconds": 20})
                await anyio.sleep(0.1)
                assert (await call("get_signature_status", {"request_id": r["request_id"]}))["status"] == "pending"
                tg.cancel_scope.cancel()
        assert time.monotonic() - t0 < 5

        async def sign_later():
            await anyio.sleep(0.4)
            await anyio.to_thread.run_sync(lambda: httpx.post(r["sign_url"] + "/submit", json=sign_body()))
        async with anyio.create_task_group() as tg:
            tg.start_soon(sign_later)
            st = await call("wait_for_signature", {"request_id": r["request_id"], "wait_seconds": 20})
        assert st["status"] == "completed", st
    anyio.run(flow)


@pytest.mark.parametrize("p", FILES)
def test_pages_markers_placeholder_multi_spot(p):
    s = p.read_text(encoding="utf-8")
    if p.name == "sign.js":
        s += (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="padPh"' in s and ">Sign here</div>" in s and "'padPh').classList.toggle('hidden', strokes.length > 0)" in s
    assert "x.onclick = goToPad" in s and "scrollIntoView({behavior: 'smooth'" in s
    assert 'id="applyAll"' in s and "I agree this signature will be applied to all ' + SPOTS + ' signature spots in this document" in s
    assert "SPOTS < 2 || $('applyAll').checked" in s
    assert "Copy reply" not in s and "backCopy" not in s




def _between(p, a, b):
    s = p.read_text(encoding="utf-8")
    m = re.search(re.escape(a) + r".*?" + re.escape(b), s, re.S)
    assert m, (p, a)
    return m.group(0), s


def test_hero_blocks_identical_and_wired():
    htmls = [FILES[0].parent / "index.html", FILES[1], FILES[2]]
    css = {_between(p, "/* hero-css:start", "/* hero-css:end */")[0] for p in htmls}
    js = {_between(p, "/* hero:start", "/* hero:end */")[0] for p in FILES[1:]}  # Local date controls differ from the hosted page
    assert len(css) == 1 and len(js) == 1
    # Outside the date controls, retain the hosted/local hero parity check.
    def without_dates(path):
        block = _between(path, "/* hero:start", "/* hero:end */")[0].split("\n", 1)[1]
        start, end = block.index("// sbdate:start"), block.index("function sbChecked")
        return block[:start] + block[end:]
    assert len({without_dates(p) for p in FILES}) == 1
    c, j = css.pop(), js.pop()
    for k in ("Inter,ui-sans-serif,-apple-system", "prefers-color-scheme:dark", "prefers-reduced-motion:reduce", "heroPulse", "#heroSheet", ".heroReceipt", "heroDraw", ".heroActions{position:sticky;bottom:0", "safe-area-inset-bottom", "--chipFs", "text-overflow:ellipsis", "heroChip.icon::before", "#heroSheet::backdrop"):
        assert k in c, k
    for k in ("'Review & sign'", "'Adopt & sign'", "async function heroFly", "prefers-reduced-motion: reduce", "showModal", "heroSheetShow", "heroEl('dialog')",
              "'Signed in ' + secs + 's", "' \\u00b7 Stayed on your device'", "M17 29l7 7 15-16", "heroThumb", "stopImmediatePropagation", "function heroFitChips", "classList.add('heroActions')", "'\\u270e Sign'", "setProperty('--chipFs'"):
        assert k in j, k
    assert "Signed <" not in j and "watermark" not in j
    for p in FILES:
        s = p.read_text(encoding="utf-8")
        assert "function goToPad(){ if (heroOpen()) return;" in s and "heroSpots(SPOTS)" in s
        b = _block(p)
        assert "if (typeof heroReceipt === 'function') heroReceipt(box);" in b
        assert "'Signed with gotoquill \\u2197'" in b and "foot.target = '_blank'" in b and "noopener" in b
