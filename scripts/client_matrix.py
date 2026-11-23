#!/usr/bin/env python3
"""Cross-assistant end-to-end matrix for gotoquill (opt-in, not part of the default pytest run).

Real agent CLIs (Goose, OpenClaw, Hermes Agent, optional Gemini CLI) talk to a local Ollama model, discover the
gotoquill MCP server, request a signature on examples/sample_contract.pdf, wait, and report the signed PDF path.
A sidecar signs the real signing page with Playwright headless Chromium as soon as the request appears.

    GOTOQUILL_CLIENT_E2E=1 .venv/bin/python scripts/client_matrix.py            # all free clients
    .venv/bin/python scripts/client_matrix.py --clients goose,hermes --retries 3 --model qwen2.5:3b

See docs/TESTING-CLIENTS.md. Results: <out>/results.md and <out>/results.json (default ./client-matrix-out/,
git-ignored). Every attempt gets its own temp home: GOTOQUILL_DATA_DIR / GOTOQUILL_CONFIG_DIR /
GOTOQUILL_CACHE_DIR, client config dirs and a copy of the sample PDF, so nothing touches ~/.config/gotoquill.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "examples" / "sample_contract.pdf"
TOOL_NAMES = ["request_signature", "get_signature_status", "wait_for_signature", "cancel_request",
              "connect_notifications", "apply_signature_response"]
PROMPT = ("Use the gotoquill tool to request a signature from Test Signer on {pdf}. Use delivery=\"page\" "
          "(the signer is at this computer, so the local page works). After it returns, call wait_for_signature "
          "with the request_id it gave you, then tell me the signed_pdf_path.")
URL_RE = re.compile(r"https?://(?:127\.0\.0\.1|localhost):\d+/s/[A-Za-z0-9_\-]+|https://[^\s\"'<>]+/gotoquill/[^\s\"'<>]*#[^\s\"'<>]+")


def sh(cmd: list[str] | str, timeout: float = 60, env: dict | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError as e:
        return 127, str(e)
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@dataclass
class Attempt:
    n: int
    ok: bool = False
    tools_discovered: bool | None = None
    request_made: bool = False
    signed: bool = False
    audit_ok: bool = False
    hashes_ok: bool = False
    path_reported: bool = False
    path_reported_how: str = ""
    agent_waited: bool = False   # the agent itself got status=completed back from wait/get_signature_status
    tool_calls: list[str] = field(default_factory=list)
    final_text: str = ""
    duration_s: float = 0.0
    sign_url_kind: str = ""
    errors: list[str] = field(default_factory=list)
    log: str = ""


@dataclass
class ClientResult:
    client: str
    version: str = ""
    status: str = "not run"   # pass | fail | skipped | not installed
    reason: str = ""
    tools_discovered: str = ""
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def pass_rate(self) -> str:
        return f"{sum(a.ok for a in self.attempts)}/{len(self.attempts)}" if self.attempts else "-"


# ---------------------------------------------------------------- sandbox per attempt
class Sandbox:
    def __init__(self, root: Path, server_cmd: list[str]):
        self.root = root
        self.doc_dir = root / "doc"
        self.doc_dir.mkdir(parents=True)
        self.pdf = self.doc_dir / SAMPLE.name
        shutil.copy(SAMPLE, self.pdf)
        self.home = root / "home"
        self.home.mkdir()
        self.capture = root / "opened_urls.txt"
        cap = root / "capture-browser.sh"
        cap.write_text(f'#!/bin/sh\nprintf "%s\\n" "$1" >> {shlex.quote(str(self.capture))}\n')
        cap.chmod(0o755)
        self.server_cmd = server_cmd
        self.server_env = {
            "GOTOQUILL_DATA_DIR": str(root / "as-data"),
            "GOTOQUILL_CONFIG_DIR": str(root / "as-config"),
            "GOTOQUILL_CACHE_DIR": str(root / "as-cache"),
            "GOTOQUILL_NO_KEYRING": "1",
            "GOTOQUILL_OPEN_BROWSER": "1",
            # webbrowser.open() honours $BROWSER (URL appended): the "browser" records the page URL for the sidecar.
            # No spaces in any value: some clients (goose --with-extension) split the command line on whitespace.
            "BROWSER": str(cap),
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv")),
        }

    def signed_pdf(self) -> Path:
        return self.doc_dir / f"{self.pdf.stem.replace('_', ' ')} - signed.pdf"

    def audit(self) -> Path:
        s = self.signed_pdf()
        return s.with_name(s.name[:-4] + ".audit.json")


# ---------------------------------------------------------------- sidecar auto-signer
class AutoSigner(threading.Thread):
    """Finds the new request's signing URL and signs the real page with Playwright headless Chromium."""

    def __init__(self, sb: Sandbox, live_log: Path, deadline: float):
        super().__init__(daemon=True)
        self.sb, self.live_log, self.deadline = sb, live_log, deadline
        self.url: str | None = None
        self.done = False
        self.error: str | None = None
        self.stop = threading.Event()

    def _find_url(self) -> str | None:
        if self.sb.capture.exists():
            for line in self.sb.capture.read_text().splitlines():
                if line.strip():
                    return line.strip()
        for st in (self.sb.root / "as-config" / "file-requests").glob("req_*/state.json"):
            try:
                u = json.loads(st.read_text()).get("sign_url")
                if u:
                    return u
            except Exception:  # noqa: BLE001 - written atomically, but be safe
                pass
        if self.live_log.exists():
            m = URL_RE.search(self.live_log.read_text(errors="replace"))
            if m:
                return m.group(0)
        return None

    def run(self) -> None:
        while not self.stop.is_set() and time.time() < self.deadline:
            self.url = self._find_url()
            if self.url:
                break
            time.sleep(0.5)
        if not self.url:
            return
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch()
                pg = b.new_page()
                pg.goto(self.url, timeout=60_000)
                pg.wait_for_selector("#app:not(.hidden)", timeout=60_000)
                pg.click("#tabType")
                pg.fill("#typed", "Test Signer")
                pg.check("#consent")
                with pg.expect_response(lambda r: r.request.method == "POST", timeout=60_000) as resp:
                    pg.click("#submit")
                if resp.value.status >= 400:
                    raise RuntimeError(f"submit returned HTTP {resp.value.status}")
                try:  # the confirmation screen; the server may already be gone if the agent exited right away
                    pg.wait_for_selector("#done:not(.hidden)", timeout=15_000)
                except Exception:  # noqa: BLE001
                    pass
                b.close()
            self.done = True
        except Exception as e:  # noqa: BLE001
            self.error = f"auto-signer: {type(e).__name__}: {e}"[:500]


# ---------------------------------------------------------------- clients
class Client:
    name = ""
    binary = ""
    optional_env: str | None = None   # skip cleanly unless this env var is set

    def __init__(self, model: str, ollama: str, provider: str = "ollama"):
        self.model, self.ollama, self.provider = model, ollama, provider

    @property
    def gem(self) -> bool:
        return self.provider == "gemini"

    def version(self) -> str:
        rc, out = sh([self.binary, "--version"])
        return out.splitlines()[-1].strip() if rc == 0 and out else ""

    def installed(self) -> bool:
        return shutil.which(self.binary) is not None

    def setup(self, sb: Sandbox) -> tuple[dict, str]:
        """Write the client's temp config. Returns (env, tools-discovered note from a probe or '')."""
        raise NotImplementedError

    def command(self, sb: Sandbox, prompt: str) -> list[str]:
        raise NotImplementedError

    def parse(self, output: str) -> tuple[str, list[str], str]:
        """(final answer text, gotoquill tool calls in order, all tool-result text). Plain-text default."""
        calls = re.findall(r"\b(" + "|".join(TOOL_NAMES) + r")\b", output)
        return output[-3000:], calls, output

    def base_env(self, sb: Sandbox) -> dict:
        env = dict(os.environ)
        env.update(XDG_CONFIG_HOME=str(sb.home / ".config"), XDG_DATA_HOME=str(sb.home / ".local/share"),
                   XDG_STATE_HOME=str(sb.home / ".local/state"), OLLAMA_HOST=self.ollama, NO_COLOR="1")
        for k in ("GOTOQUILL_DATA_DIR", "GOTOQUILL_CONFIG_DIR", "GOTOQUILL_CACHE_DIR"):
            env[k] = sb.server_env[k]   # the client's own env too, in case it doesn't pass "env" through
        return env


class Goose(Client):
    name, binary = "goose", "goose"

    def setup(self, sb):
        env = self.base_env(sb)
        if self.gem:  # key stays in the process env only, never in files or argv
            env.setdefault("GOOGLE_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
        env.update(GOOSE_PROVIDER="google" if self.gem else "ollama", GOOSE_MODEL=self.model, GOOSE_DISABLE_KEYRING="1", GOOSE_MODE="auto",
                   GOOSE_CLI_MIN_PRIORITY="0.0")
        return env, ""

    def command(self, sb, prompt):
        ext = " ".join(f"{k}={shlex.quote(v)}" for k, v in sb.server_env.items()) + " " + shlex.join(sb.server_cmd)
        return ["goose", "run", "--no-session", "--no-profile", "--provider", "google" if self.gem else "ollama", "--model", self.model,
                "--max-turns", "15", "--output-format", "json", "--with-extension", ext, "-t", prompt]


    def parse(self, output):
        try:
            d = json.loads(output[output.index("{"):output.rindex("}") + 1])
        except Exception:  # noqa: BLE001
            return super().parse(output)
        calls, results, final = [], [], ""
        for m in d.get("messages", []):
            for c in m.get("content", []):
                if c.get("type") == "toolRequest":
                    calls.append(str(((c.get("toolCall") or {}).get("value") or {}).get("name", "")).split("__")[-1])
                elif c.get("type") == "toolResponse":
                    results.append(json.dumps(c.get("toolResult")))
                elif c.get("type") == "text" and m.get("role") == "assistant":
                    final = c.get("text", "")
        return final, calls, "\n".join(results)


class OpenClaw(Client):
    name, binary = "openclaw", "openclaw"

    def version(self):
        rc, out = sh(["openclaw", "--version"])
        return out.split("(")[0].strip() if rc == 0 else ""

    def setup(self, sb):
        env = self.base_env(sb)
        st = sb.home / ".openclaw"
        st.mkdir(parents=True, exist_ok=True)
        (sb.root / "oc-ws").mkdir(parents=True, exist_ok=True)
        env.update(OPENCLAW_STATE_DIR=str(st), OPENCLAW_CONFIG_PATH=str(st / "openclaw.json"),
                   OLLAMA_API_KEY="ollama-local", OLLAMA_BASE_URL=self.ollama)
        cfg = {"models": {"providers": {"ollama": {"baseUrl": self.ollama, "api": "ollama", "apiKey": "ollama-local",
                                                   "models": [{"id": self.model, "name": self.model}]}}},
               "agents": {"defaults": {"model": {"primary": f"ollama/{self.model}"}, "workspace": str(sb.root / "oc-ws")}}}
        if self.gem:
            cfg = {"agents": {"defaults": {"model": {"primary": f"google/{self.model}"},
                                           "workspace": str(sb.root / "oc-ws")}}}
        (st / "openclaw.json").write_text(json.dumps(cfg, indent=2))
        # OpenClaw drops BROWSER from stdio server env ("blocked for startup safety"), so pass it via env(1)
        browser = sb.server_env.get("BROWSER")
        argv = (["env", f"BROWSER={browser}"] if browser else []) + list(sb.server_cmd)
        cmd = ["openclaw", "mcp", "add", os.environ.get("GOTOQUILL_MATRIX_SERVER_NAME", "gotoquill"), "--command", argv[0], "--timeout", "900"]
        for a in argv[1:]:
            cmd += ["--arg", a]
        for k, v in sb.server_env.items():
            if k != "BROWSER":
                cmd += ["--env", f"{k}={v}"]
        rc, out = sh(cmd, timeout=240, env=env)
        note = f"mcp add rc={rc}"
        rc2, out2 = sh(["openclaw", "mcp", "doctor", "--probe"], timeout=240, env=env)
        found = [t for t in TOOL_NAMES if t in out2]
        note += f"; doctor --probe rc={rc2}; tools seen: {len(found)}/{len(TOOL_NAMES)}"
        (sb.root / "openclaw-setup.log").write_text(out + "\n----\n" + out2)
        return env, note

    def command(self, sb, prompt):
        return ["openclaw", "agent", "exec", "--model", f"{'google' if self.gem else 'ollama'}/{self.model}", "--cwd", str(sb.root / "oc-ws"),
                "--timeout", "900", prompt]


class Hermes(Client):
    name, binary = "hermes", "hermes"

    def version(self):
        rc, out = sh(["hermes", "--version"])
        return out.splitlines()[0].strip() if rc == 0 and out else ""

    def setup(self, sb):
        env = self.base_env(sb)
        hh = sb.home / ".hermes"
        hh.mkdir(parents=True, exist_ok=True)
        real = Path.home() / ".hermes"
        # HERMES_HOME isolates config/sessions/memory; the code install stays in ~/.hermes/hermes-agent
        env.update(HERMES_HOME=str(hh))
        if (real / "hermes-agent").exists() and not (hh / "hermes-agent").exists():
            (hh / "hermes-agent").symlink_to(real / "hermes-agent")
        q = json.dumps
        server_env = "\n".join(f"      {k}: {q(v)}" for k, v in sb.server_env.items())
        base = "https://generativelanguage.googleapis.com/v1beta/openai" if self.gem else self.ollama + "/v1"
        ctx = "  context_length: 1048576\n" if self.gem else "  context_length: 65536\n  ollama_num_ctx: 65536\n"
        (hh / "config.yaml").write_text(
            (f"model:\n  default: {q(self.model)}\n  provider: gemini\n" if self.gem else
             f"model:\n  default: {q(self.model)}\n  provider: custom\n  base_url: {q(base)}\n")
            # Hermes refuses models served with < 64K context; ask Ollama for 64K per request
            + ctx +
            f"mcp_servers:\n  gotoquill:\n    command: {q(sb.server_cmd[0])}\n    args: {q(sb.server_cmd[1:])}\n"
            f"    timeout: 900\n    connect_timeout: 120\n    env:\n{server_env}\n")
        if self.gem:  # env only, never written to disk
            pass  # Hermes' built-in gemini provider reads GEMINI_API_KEY from the env
        else:
            (hh / ".env").write_text("OPENAI_API_KEY=ollama-local\n")
        rc, out = sh(["hermes", "mcp", "test", "gotoquill"], timeout=180, env=env)
        found = [t for t in TOOL_NAMES if t in out]
        (sb.root / "hermes-setup.log").write_text(out)
        return env, f"hermes mcp test rc={rc}; tools seen: {len(found)}/{len(TOOL_NAMES)}"

    def command(self, sb, prompt):
        return ["hermes", "chat", "-Q", "--yolo", "--max-turns", "12", "-q", prompt]


class Gemini(Client):
    name, binary, optional_env = "gemini", "gemini", "GEMINI_API_KEY"

    def setup(self, sb):
        env = self.base_env(sb)
        env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"  # headless temp sandbox
        gdir = sb.root / ".gemini"
        gdir.mkdir(exist_ok=True)
        (gdir / "settings.json").write_text(json.dumps({"mcpServers": {"gotoquill": {
            "command": sb.server_cmd[0], "args": sb.server_cmd[1:], "env": sb.server_env, "timeout": 900_000,
            "trust": True}}, **({"security": {"auth": {"selectedType": "gemini-api-key"}}} if self.gem else {})},
            indent=2))
        return env, ""

    def command(self, sb, prompt):
        return ["gemini", "--yolo", "-m", self.model, "-p", prompt] if self.gem else ["gemini", "--yolo", "-p", prompt]


class Direct(Client):
    """Control row: a plain MCP client with no model, proves the server + auto-signer path on this box."""
    name, binary = "direct", sys.executable

    def version(self):
        rc, out = sh([sys.executable, "-c", "import importlib.metadata as m; print('mcp', m.version('mcp'))"])
        return out if rc == 0 else ""

    def setup(self, sb):
        env = self.base_env(sb)
        env.update(sb.server_env)
        return env, ""

    def command(self, sb, prompt):
        return [sys.executable, str(REPO / "tests" / "clients" / "direct_mcp_client.py"), str(sb.pdf), "--",
                *sb.server_cmd]


CLIENTS = {c.name: c for c in (Direct, Goose, OpenClaw, Hermes, Gemini)}


# ---------------------------------------------------------------- runner
def inferred_wait(final, sb) -> bool:
    """Quiet clients (openclaw/hermes -Q) don't echo tool results; accept a final answer that
    says the request completed AND names the real signed file, which it can only know from
    wait_for_signature / get_signature_status / the auto-waiting request_signature."""
    p = sb.signed_pdf()
    if not p.exists() or not (str(p) in final or p.name in final):
        return False
    claim = final.replace(str(p), " ").replace(p.name, " ")  # the filename itself contains "signed"
    return bool(re.search(r"\b(completed|signed)\b", claim, re.I))


def check_outputs(sb: Sandbox, a: Attempt, output: str) -> None:
    signed, audit = sb.signed_pdf(), sb.audit()
    a.signed = signed.exists() and signed.stat().st_size > 0
    a.audit_ok = audit.exists()
    if a.signed and a.audit_ok:
        try:
            blob = json.loads(audit.read_text())
            flat = json.dumps(blob)
            a.hashes_ok = sha256(sb.pdf) in flat and sha256(signed) in flat
            if not a.hashes_ok:
                a.errors.append("audit hashes do not match the original/signed files")
        except Exception as e:  # noqa: BLE001
            a.errors.append(f"audit unreadable: {e}")
    if str(signed) in output:
        a.path_reported, a.path_reported_how = True, "full path"
    elif signed.name in output:
        a.path_reported, a.path_reported_how = True, "file name only"
    elif "signed.pdf" in output or "signed_pdf_path" in output:
        a.path_reported_how = "mentions signed pdf, path differs"
    else:
        a.path_reported_how = "not mentioned"


def run_attempt(client: Client, n: int, out_dir: Path, server_cmd: list[str], timeout: float, keep: bool) -> tuple[Attempt, str]:
    a = Attempt(n)
    root = Path(tempfile.mkdtemp(prefix=f"as-{client.name}-{n}-"))
    sb = Sandbox(root, server_cmd)
    probe_note = ""
    try:
        env, probe_note = client.setup(sb)
        prompt = PROMPT.format(pdf=sb.pdf)
        log_path = out_dir / f"{client.name}-attempt{n}.log"
        log_path.write_text("")  # truncate before the sidecar starts reading it
        start = time.time()
        signer = AutoSigner(sb, log_path, start + timeout)
        signer.start()
        with open(log_path, "a") as lf:
            lf.write(f"$ {shlex.join(client.command(sb, '<prompt>'))}\nPROMPT: {prompt}\n\n")
            lf.flush()
            try:
                p = subprocess.run(client.command(sb, prompt), stdout=lf, stderr=subprocess.STDOUT, text=True,
                                   timeout=timeout, env=env, cwd=root, stdin=subprocess.DEVNULL)
                rc = p.returncode
            except subprocess.TimeoutExpired:
                rc = 124
                a.errors.append(f"client timed out after {timeout:.0f}s")
        a.duration_s = round(time.time() - start, 1)
        signer.stop.set()
        signer.join(timeout=90)
        output = log_path.read_text(errors="replace")
        if rc not in (0, 124):
            a.errors.append(f"client exit code {rc}")
        a.request_made = bool(signer.url) or (root / "as-data" / "docs").exists() and any((root / "as-data" / "docs").iterdir())
        if signer.url:
            a.sign_url_kind = "local page" if "127.0.0.1" in signer.url else "link"
        if signer.error:
            a.errors.append(signer.error)
        body = output.split("PROMPT:", 1)[1].split("\n", 1)[1] if "PROMPT:" in output else output
        final, calls, results = client.parse(body)
        a.tool_calls, a.final_text = calls, final.strip()[-1500:]
        m = re.search(r"tools seen: (\d+)/", probe_note or "")
        a.tools_discovered = bool(calls) or a.request_made or bool(m and int(m.group(1)) > 0)
        a.agent_waited = bool(re.search(r'\\?"status\\?":\s*\\?"completed|(?:wait_for_signature|get_signature_status) -> completed', results))
        check_outputs(sb, a, final)
        if not a.agent_waited and a.signed:
            a.agent_waited = inferred_wait(final, sb)
            if a.agent_waited:
                a.errors.append("waited inferred from final answer (client hides tool results)")
        a.ok = a.request_made and a.signed and a.audit_ok and a.hashes_ok and a.agent_waited
        a.log = str(log_path.relative_to(out_dir.parent)) if out_dir.parent in log_path.parents else str(log_path)
        if not a.request_made:
            a.errors.append("no signature request was created (model did not call request_signature)")
        elif not a.signed:
            a.errors.append("request created but no signed PDF")
        elif not a.agent_waited:
            a.errors.append("signed (server watcher stamped it) but the agent never got status=completed back")
    except Exception as e:  # noqa: BLE001
        a.errors.append(f"harness: {type(e).__name__}: {e}")
    finally:
        kill_sandbox_procs(root)
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
    return a, probe_note


def kill_sandbox_procs(root: Path) -> None:
    """Clients leave helpers behind (Hermes' idle-exit gateway, MCP servers); stop anything whose environment
    points into this attempt's sandbox so the next attempt starts clean."""
    import signal
    needle = str(root).encode()
    for p in Path("/proc").glob("[0-9]*"):
        try:
            if int(p.name) != os.getpid() and needle in (p / "environ").read_bytes():
                os.kill(int(p.name), signal.SIGTERM)
        except (OSError, ValueError):
            pass


def ollama_ok(url: str, model: str) -> str | None:
    import urllib.request
    try:
        with urllib.request.urlopen(url + "/api/tags", timeout=5) as r:
            names = [m["name"] for m in json.load(r)["models"]]
    except Exception as e:  # noqa: BLE001
        return f"Ollama not reachable at {url}: {e}"
    if model not in names and f"{model}:latest" not in names:
        return f"model {model} not pulled (have: {', '.join(names) or 'none'}); run: ollama pull {model}"
    return None


def write_reports(out_dir: Path, results: list[ClientResult], meta: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    data = {"meta": meta, "clients": [dict(asdict(r), pass_rate=r.pass_rate) for r in results]}
    (out_dir / "results.json").write_text(json.dumps(data, indent=2))
    yn = lambda v: "-" if v is None else ("yes" if v else "no")  # noqa: E731
    lines = [f"# gotoquill client matrix", "",
             f"model `{meta['model']}` via Ollama {meta.get('ollama_version', '')} · server `{meta['server_cmd']}` · "
             f"total {meta['total_s']}s · {meta['started']}", "",
             "| client | version | status | pass rate | tools discovered | request made | signed + audit + hashes | agent waited | path reported | duration (s) | notes |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        best = next((a for a in r.attempts if a.ok), r.attempts[-1] if r.attempts else None)
        if best is None:
            lines.append(f"| {r.client} | {r.version or '-'} | {r.status} | - | - | - | - | - | - | - | {r.reason} |")
            continue
        durs = "/".join(str(a.duration_s) for a in r.attempts)
        notes = "; ".join(dict.fromkeys(e for a in r.attempts for e in a.errors))[:300] or r.reason
        lines.append(f"| {r.client} | {r.version} | {r.status} | {r.pass_rate} | {yn(best.tools_discovered)}"
                     f"{' (' + r.tools_discovered + ')' if r.tools_discovered else ''} | {yn(best.request_made)} | "
                     f"{yn(best.signed and best.audit_ok and best.hashes_ok)} | {yn(best.agent_waited)} | {best.path_reported_how} | {durs} | "
                     f"{notes.replace('|', '/')} |")
    lines += ["", "Logs per attempt: `" + str(out_dir) + "/<client>-attemptN.log`."]
    (out_dir / "results.md").write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clients", default="direct,goose,openclaw,hermes,gemini")
    ap.add_argument("--model", default=os.environ.get("GOTOQUILL_MATRIX_MODEL", "qwen2.5:3b"))
    ap.add_argument("--provider", choices=["ollama", "gemini"], default="ollama",
                    help="gemini: point every client at the Gemini API (GEMINI_API_KEY from env; never written)")
    ap.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    ap.add_argument("--retries", type=int, default=3, help="attempts per client until one passes (default 3)")
    ap.add_argument("--all-attempts", action="store_true", help="run every attempt even after a pass (pass rate)")
    ap.add_argument("--timeout", type=float, default=900, help="seconds per attempt")
    ap.add_argument("--server-cmd", default=f"uvx --from {REPO} gotoquill mcp")
    ap.add_argument("--out", default=str(REPO / "client-matrix-out"))
    ap.add_argument("--server-name", default=None,
                    help="MCP server name to register in OpenClaw (default gotoquill; weak models often guess gotoquill)")
    ap.add_argument("--keep", action="store_true", help="keep temp sandboxes")
    args = ap.parse_args(argv)
    if args.server_name:
        os.environ["GOTOQUILL_MATRIX_SERVER_NAME"] = args.server_name

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    server_cmd = shlex.split(args.server_cmd)
    meta = {"model": args.model, "server_cmd": args.server_cmd, "started": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "ollama_version": sh(["ollama", "--version"])[1].splitlines()[-1] if shutil.which("ollama") else ""}
    t0 = time.time()
    if server_cmd[0] == "uvx" and shutil.which("uv"):
        sh(["uv", "cache", "clean", "gotoquill"], timeout=120)  # uvx caches local builds; pick up edits
    err = None if args.provider == "gemini" else ollama_ok(args.ollama, args.model)
    results: list[ClientResult] = []
    for name in [c.strip() for c in args.clients.split(",") if c.strip()]:
        client = CLIENTS[name](args.model, args.ollama, args.provider)
        r = ClientResult(name)
        results.append(r)
        if client.optional_env and not os.environ.get(client.optional_env):
            r.status, r.reason = "skipped", f"{client.optional_env} not set (optional target)"
            print(f"[{name}] skipped: {r.reason}", flush=True)
            continue
        if not client.installed():
            r.status, r.reason = "not installed", f"`{client.binary}` not on PATH"
            print(f"[{name}] not installed", flush=True)
            continue
        if err and name != "gemini":
            r.status, r.reason = "fail", err
            continue
        r.version = client.version()
        for n in range(1, args.retries + 1):
            print(f"[{name}] attempt {n}/{args.retries} ...", flush=True)
            a, note = run_attempt(client, n, out_dir, server_cmd, args.timeout, args.keep)
            r.tools_discovered = r.tools_discovered or note
            r.attempts.append(a)
            print(f"[{name}] attempt {n}: ok={a.ok} request={a.request_made} signed={a.signed} "
                  f"waited={a.agent_waited} calls={a.tool_calls} path={a.path_reported_how} {a.duration_s}s {'; '.join(a.errors)}", flush=True)
            if a.ok and not args.all_attempts:
                break
        r.status = "pass" if any(a.ok for a in r.attempts) else "fail"
        meta["total_s"] = round(time.time() - t0, 1)
        write_reports(out_dir, results, meta)
    meta["total_s"] = round(time.time() - t0, 1)
    write_reports(out_dir, results, meta)
    print((out_dir / "results.md").read_text())
    return 0 if all(r.status in ("pass", "skipped", "not installed") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
