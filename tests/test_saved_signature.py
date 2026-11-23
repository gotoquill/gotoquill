import asyncio
import json
import stat

import httpx
import pytest

from test_flow import _mcp_call, sig_png, sign_body


class FakeKeyring:
    """In-memory stand-in for the OS keychain."""
    priority = 10

    def __init__(self):
        self.store = {}

    def get_password(self, s, u):
        return self.store.get((s, u))

    def set_password(self, s, u, p):
        self.store[(s, u)] = p

    def get_keyring(self):
        return self


@pytest.fixture()
def fake_keyring(monkeypatch):
    from gotoquill import vault
    kr = FakeKeyring()
    monkeypatch.setattr(vault, "_keyring", lambda: kr)
    return kr


def _req(env, pdf_file):
    r = env.request(pdf_path=str(pdf_file), signer_name="Alex Example")
    return r, r["sign_url"]


def _audit(pdf_file):
    return json.loads(pdf_file.with_name("contract - signed.audit.json").read_text())


def test_shared_page_cannot_read_use_or_overwrite_owner_vault(env, pdf_file):
    from gotoquill import vault
    vault.save("signature", sig_png(), "drawn", "Alex Morgan")
    r, url = _req(env, pdf_file)
    for _ in range(2):
        info = httpx.get(url + "/info").json()
        assert "saved_signatures" not in info and "vault_nonce" not in info
        assert info["save_names"] == []
    for body in (sign_body(save_as="signature"),
                 {"decision": "sign", "use_saved": "signature", "vault_nonce": "guess", "consent": True}):
        assert httpx.post(url + "/submit", json=body).status_code == 403
    assert vault.get_png("signature") == sig_png()
    assert httpx.post(url + "/submit", json=sign_body()).json()["status"] == "signed"
    assert env.status(r["request_id"], wait_seconds=10)["status"] == "completed"


def test_permissions_and_plain_fallback(env, pdf_file):
    from gotoquill import vault
    vault.save("signature", sig_png(), "drawn", "Alex")
    vault.save("initials", sig_png(), "typed", "SL")
    p = vault.vault_path()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    raw = json.loads(p.read_text())
    assert raw["encrypted"] is False and "Plain local file" in raw["note"]
    assert {x["name"] for x in vault.info()["signatures"]} == {"signature", "initials"}


def test_encrypted_with_keychain(env, fake_keyring):
    from gotoquill import vault
    vault.save("signature", sig_png(), "drawn", "Alex")
    raw = json.loads(vault.vault_path().read_text())
    assert raw["encrypted"] is True and "signatures" not in raw and "iVBOR" not in vault.vault_path().read_text()
    assert stat.S_IMODE(vault.vault_path().stat().st_mode) == 0o600
    assert vault.get_png("signature") == sig_png()
    fake_keyring.store.clear()  # key gone -> cannot decrypt, page simply shows nothing
    assert vault.previews() == [] and "error" in vault.info()


def test_only_local_owner_cli_can_delete(env, pdf_file, capsys):
    from gotoquill import cli, vault
    vault.save("signature", sig_png(), "drawn", "Alex")
    vault.save("initials", sig_png(), "drawn", "SL")
    r, url = _req(env, pdf_file)
    assert "vault_nonce" not in httpx.get(url + "/info").json()
    assert httpx.post(url + "/saved/delete", json={"vault_nonce": "wrong", "name": "initials"}).status_code == 403
    assert {x["name"] for x in vault.info()["signatures"]} == {"signature", "initials"}
    cli.main(["signature", "show"])
    out = capsys.readouterr().out
    shown = json.loads(out)
    assert shown["path"] == str(vault.vault_path()) and shown["permissions"] == "0o600"
    assert "iVBOR" not in out and "data:image" not in out  # metadata only, never the picture
    cli.main(["signature", "delete"])
    assert "signature" in capsys.readouterr().out and not vault.vault_path().exists()
    env.cancel(r["request_id"])


def test_agent_cannot_use_saved_signature_without_page_click(env, pdf_file):
    """Neither the first nor later MCP view grants owner authentication."""
    from gotoquill import vault
    from gotoquill.mcp_server import build_server
    vault.save("signature", sig_png(), "drawn", "Alex")
    srv = build_server()
    call = _mcp_call(srv)

    async def flow():
        req = await call("request_signature", {"pdf_path": str(pdf_file), "open_browser": False, "delivery": "page"})
        assert "iVBOR" not in json.dumps(req) and "vault_nonce" not in req
        tok = req["sign_token"]
        # agent tries to sign with the saved signature: no nonce / guessed nonce -> refused
        for n in (None, "guess"):
            r = await call("ui_submit_signature", {"sign_token": tok, "decision": "sign", "use_saved": "signature",
                                                   "vault_nonce": n, "consent": True})
            assert r.get("code") == 403
        # HTTP path too
        assert httpx.post(req["sign_url"] + "/submit", json={"decision": "sign", "use_saved": "signature",
                                                             "consent": True}).status_code == 403
        # the in-chat view loads first and gets the nonce + preview; a second (agent) call gets nothing
        view = await call("ui_load_document", {"sign_token": tok})
        assert "vault_nonce" not in view and "saved_signatures" not in view
        again = await call("ui_load_document", {"sign_token": tok})
        assert "vault_nonce" not in again and "saved_signatures" not in again
        st = await call("get_signature_status", {"request_id": req["request_id"]})
        assert st["status"] == "pending" and "iVBOR" not in json.dumps(st)
        denied = await call("ui_submit_signature", {"sign_token": tok, "decision": "sign", "use_saved": "signature",
                                                   "vault_nonce": "guess", "consent": True})
        assert denied.get("code") == 403
        await call("cancel_request", {"request_id": req["request_id"]})

    asyncio.run(flow())
