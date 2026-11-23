import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from gotoquill import connect as C
from gotoquill import notify
from gotoquill import targets as T

ROOT = Path(__file__).resolve().parents[1]
SECRET = "s3cr3t-token-value-XYZ"


@pytest.fixture()
def server():
    got = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            got.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}", got
    s.shutdown()


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("GOTOQUILL_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("GOTOQUILL_NO_KEYRING", "1")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for v in ("OPENCLAW_CONFIG_PATH", "OPENCLAW_STATE_DIR", "OPENCLAW_HOME", "OPENCLAW_GATEWAY_PORT"):
        monkeypatch.delenv(v, raising=False)
    return tmp_path


def test_header_env_resolution(cfg, monkeypatch):
    monkeypatch.setenv("WAKE_AUTH", "Bearer " + SECRET)
    h, missing = T.resolve_headers({"Authorization": "env:WAKE_AUTH", "X-A": "lit", "X-B": "env:NOPE_UNSET"})
    assert h["Authorization"] == "Bearer " + SECRET and h["X-A"] == "lit"
    assert "X-B" not in h and missing == ["NOPE_UNSET"]
    with pytest.raises(T.TargetError):
        T.check_headers({"X-Bad": "a\r\nInjected: 1"})
    assert T.mask_value("literal") == "***" and T.mask_value("env:WAKE_AUTH") == "env:WAKE_AUTH"


def test_hmac(cfg):
    key = T.secret()
    assert key and T.secret() == key and len(key) >= 32
    sig = T.sign(b"{}", "123", key)
    assert sig.startswith("sha256=")
    import time
    ts = str(int(time.time()))
    s = T.sign(b'{"a":1}', ts, key)
    assert T.verify(b'{"a":1}', ts, s, key)
    assert not T.verify(b'{"a":2}', ts, s, key)
    assert not T.verify(b'{"a":1}', ts, s, "other")


def test_saved_targets_applied_automatically(cfg, server, monkeypatch):
    url, got = server
    monkeypatch.setenv("WAKE_AUTH", SECRET)
    r = C.connect(webhook=url + "/wake", headers={"Authorization": "env:WAKE_AUTH"},
                  body={"text": "{{message}}", "rid": "{{request_id}}"}, openclaw=False)
    assert r["ok"] and r["tests"][0]["ok"], r
    assert got[0]["headers"]["authorization"] == SECRET
    got.clear()
    h = notify.save_hooks("req_auto001")
    assert h and h.get("saved_targets")
    assert notify.maybe_fire("req_auto001", {"status": "completed", "request_id": "req_auto001",
                                           "signed_pdf_path": "/tmp/x.signed.pdf", "next": "send it"})
    assert len(got) == 1
    req = got[0]
    body = json.loads(req["body"])
    assert body["rid"] == "req_auto001" and "signed" in body["text"].lower()
    assert T.verify(req["body"], req["headers"]["x-gotoquill-timestamp"],
                    req["headers"]["x-gotoquill-signature"], T.secret(create=False))
    # explicit hooks win over saved targets
    assert not (notify.save_hooks("req_auto002", command="true") or {}).get("saved_targets")
    log = (notify._rdir("req_auto001") / "hook-result.json").read_text()
    assert SECRET not in log
    assert SECRET not in json.dumps(T.status())


def _cli(args, cfg, env_extra=None):
    env = dict(os.environ, GOTOQUILL_CONFIG_DIR=str(cfg / "config"), GOTOQUILL_NO_KEYRING="1",
               HOME=str(cfg / "home"), **(env_extra or {}))
    for v in ("OPENCLAW_CONFIG_PATH", "OPENCLAW_STATE_DIR", "OPENCLAW_HOME"):
        env.pop(v, None)
    return subprocess.run([sys.executable, "-m", "gotoquill.cli", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)


def test_cli_connect_webhook(cfg, server):
    url, got = server
    p = _cli(["connect", "--webhook", url + "/hook", "--header", "X-Key=" + SECRET,
              "--header-env", "Authorization=WAKE_AUTH"], cfg, {"WAKE_AUTH": "Bearer " + SECRET})
    assert p.returncode == 0, p.stdout + p.stderr
    assert SECRET not in p.stdout + p.stderr
    assert got and got[0]["headers"]["x-key"] == SECRET and got[0]["headers"]["authorization"] == "Bearer " + SECRET
    assert "x-gotoquill-signature" in got[0]["headers"]
    st = _cli(["connect", "--status"], cfg)
    assert st.returncode == 0 and SECRET not in st.stdout and "/hook" not in st.stdout
    assert len(json.loads(st.stdout)["targets"]) == 1
    rm = _cli(["connect", "--remove"], cfg)
    assert rm.returncode == 0 and json.loads(_cli(["connect", "--status"], cfg).stdout)["targets"] == []


def test_openclaw_writer(cfg, server, monkeypatch):
    url, got = server
    home = cfg / "home" / ".openclaw"
    home.mkdir(parents=True)
    conf = home / "openclaw.json"
    conf.write_text(json.dumps({"gateway": {"port": 18789}, "agents": {"x": 1}}))
    r = C.connect(openclaw_url_=url + "/hooks/gotoquill")
    assert r.get("openclaw", {}).get("needs_confirmation"), r
    assert "gotoquill" in r["openclaw"]["plan"]
    assert json.loads(conf.read_text()) == {"gateway": {"port": 18789}, "agents": {"x": 1}}
    assert T.targets() == []
    r = C.connect(openclaw_url_=url + "/hooks/gotoquill", yes=True)
    assert r["ok"], r
    new = json.loads(conf.read_text())
    assert new["agents"] == {"x": 1}
    hk = new["hooks"]
    assert hk["enabled"] and hk["token"] and hk["mappings"][0]["id"] == "gotoquill"
    backups = list(home.glob("openclaw.json.gotoquill-backup-*"))
    assert len(backups) == 1 and json.loads(backups[0].read_text())["agents"] == {"x": 1}
    assert oct(backups[0].stat().st_mode & 0o777) == "0o600"
    assert got and got[0]["headers"]["authorization"] == "Bearer " + hk["token"]
    assert json.loads(got[0]["body"])["source"] == "gotoquill"
    assert hk["token"] not in json.dumps(r) and hk["token"] not in json.dumps(T.status())
    # idempotent: second run changes nothing and makes no new backup
    C.connect(openclaw_url_=url + "/hooks/gotoquill", yes=True, test=False)
    assert json.loads(conf.read_text())["hooks"]["token"] == hk["token"]
    assert len(list(home.glob("openclaw.json.gotoquill-backup-*"))) == 1


def test_openclaw_cli_gate(cfg):
    home = cfg / "home" / ".openclaw"
    home.mkdir(parents=True)
    (home / "openclaw.json").write_text("{}")
    p = _cli(["connect", "--no-test"], cfg)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "--yes" in p.stdout + p.stderr
    p = _cli(["connect", "--no-test", "--yes"], cfg)
    assert p.returncode == 0, p.stdout + p.stderr
    tok = json.loads((home / "openclaw.json").read_text())["hooks"]["token"]
    assert tok not in p.stdout + p.stderr
