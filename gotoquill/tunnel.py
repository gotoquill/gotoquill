"""Opt-in "phone link": a temporary Cloudflare quick tunnel to one local signing page.

`cloudflared tunnel --url http://127.0.0.1:<port>` gives a random https://<words>.trycloudflare.com
address (free, no account). Traffic is encrypted (HTTPS) and passes through Cloudflare; nothing is stored there.
The cloudflared binary is used from PATH / GOTOQUILL_CLOUDFLARED, or downloaded once from the official
GitHub release (github.com/cloudflare/cloudflared) into the user cache dir and checked against its SHA-256.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
from pathlib import Path

from .core import SignError

REPO = "cloudflare/cloudflared"
URL_RE = re.compile(r"https://([a-z0-9-]+\.trycloudflare\.com)")
CONNECTED_RE = re.compile(r"Registered tunnel connection|Connection [0-9a-f-]+ registered")
HELP = ("Could not start the phone link (Cloudflare quick tunnel): {why}. Options: check this computer has "
        "internet access to github.com and *.trycloudflare.com, install cloudflared yourself and put it on PATH "
        "(or set GOTOQUILL_CLOUDFLARED=/path/to/cloudflared), or sign on this computer without share_link.")


class TunnelError(SignError):
    def __init__(self, why: str):
        super().__init__(HELP.format(why=why), 502)


def cache_dir() -> Path:
    from .envcompat import env_get
    if env_get("CACHE_DIR"):
        return Path(env_get("CACHE_DIR")).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "gotoquill"


def asset_name() -> str:
    m = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64",
            "i386": "386", "i686": "386", "armv7l": "arm", "armv6l": "arm"}.get(m)
    if not arch:
        raise TunnelError(f"unsupported CPU architecture {m!r}")
    if sys.platform.startswith("linux"):
        return f"cloudflared-linux-{arch}"
    if sys.platform == "darwin":
        return f"cloudflared-darwin-{arch}.tgz"
    if sys.platform == "win32":
        return f"cloudflared-windows-{arch}.exe"
    raise TunnelError(f"unsupported OS {sys.platform!r}")


def _get(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "gotoquill", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https URLs)
        return r.read()


def expected_sha256(release: dict, name: str) -> str:
    for a in release.get("assets", []):
        if a.get("name") == name and str(a.get("digest", "")).startswith("sha256:"):
            return a["digest"].split(":", 1)[1].lower()
    m = re.search(re.escape(name) + r":\s*([0-9a-f]{64})", release.get("body") or "")
    if m:
        return m.group(1)
    raise TunnelError(f"no SHA-256 published for {name} in release {release.get('tag_name')}")


def download_cloudflared(dest_dir: Path | None = None, fetch=_get) -> Path:
    name = asset_name()
    release = json.loads(fetch(f"https://api.github.com/repos/{REPO}/releases/latest"))
    want = expected_sha256(release, name)
    url = f"https://github.com/{REPO}/releases/download/{release['tag_name']}/{name}"
    data = fetch(url, 300)
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise TunnelError(f"checksum mismatch for {name} (expected {want}, got {got})")
    if name.endswith(".tgz"):
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            member = next(m for m in tf.getmembers() if Path(m.name).name == "cloudflared" and m.isfile())
            data = tf.extractfile(member).read()  # type: ignore[union-attr]
    d = (dest_dir or cache_dir() / "bin")
    d.mkdir(parents=True, exist_ok=True)
    out = d / ("cloudflared.exe" if sys.platform == "win32" else "cloudflared")
    tmp = out.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(tmp, out)
    (d / "cloudflared.version").write_text(f"{release['tag_name']} {want}\n")
    return out


_dl_lock = threading.Lock()


def find_cloudflared(auto_download: bool = True) -> Path:
    from .envcompat import env_get
    env = env_get("CLOUDFLARED")
    if env:
        return Path(env)
    on_path = shutil.which("cloudflared")
    if on_path:
        return Path(on_path)
    cached = cache_dir() / "bin" / ("cloudflared.exe" if sys.platform == "win32" else "cloudflared")
    if cached.exists():
        return cached
    if not auto_download:
        raise TunnelError("cloudflared is not installed")
    with _dl_lock:
        if cached.exists():
            return cached
        try:
            return download_cloudflared()
        except TunnelError:
            raise
        except Exception as e:  # noqa: BLE001
            raise TunnelError(f"downloading cloudflared failed ({e})") from e


class CloudflareTunnel:
    """One quick tunnel process. start() returns the public https URL."""

    name = "cloudflare-quick-tunnel"

    def __init__(self, port: int, binary: Path | None = None, timeout: float = 45):
        self.port, self.binary, self.timeout = port, binary, timeout
        self.proc: subprocess.Popen | None = None
        self.url: str | None = None
        self.hostname: str | None = None
        self._log: list[str] = []

    def start(self) -> str:
        binary = self.binary or find_cloudflared()
        cmd = [str(binary), "tunnel", "--no-autoupdate"]
        from .envcompat import env_get as _eg
        if _eg("TUNNEL_PROTOCOL"):  # e.g. http2 when UDP/QUIC is blocked
            cmd += ["--protocol", _eg("TUNNEL_PROTOCOL")]
        cmd += ["--url", f"http://127.0.0.1:{self.port}"]
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                         text=True, bufsize=1)
        except OSError as e:
            raise TunnelError(f"could not run {binary} ({e})") from e
        found = threading.Event()
        connected = threading.Event()

        def reader():
            assert self.proc and self.proc.stderr
            for line in self.proc.stderr:
                if len(self._log) < 200:
                    self._log.append(line.rstrip())
                if not self.url:
                    m = URL_RE.search(line)
                    if m and m.group(1) != "api.trycloudflare.com":
                        self.hostname, self.url = m.group(1), m.group(0)
                        found.set()
                if CONNECTED_RE.search(line):
                    connected.set()
            found.set()
            connected.set()

        threading.Thread(target=reader, daemon=True, name=f"cloudflared-{self.port}").start()
        found.wait(self.timeout)
        if not self.url:
            tail = " | ".join(self._log[-3:]) or "no output"
            self.stop()
            raise TunnelError(f"cloudflared gave no public URL ({tail})")
        # a URL is handed out before the tunnel is connected; wait until Cloudflare's edge accepts the connection
        connected.wait(self.timeout)
        if not (self.running and any(CONNECTED_RE.search(x) for x in self._log)):
            self.stop()
            raise TunnelError("cloudflared could not connect to Cloudflare (outbound port 7844 UDP/TCP seems "
                              "blocked by this network)")
        return self.url

    def wait_ready(self, timeout: float = 20) -> bool:
        """Quick-tunnel DNS can take a few seconds; True once the public URL answers."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                urllib.request.urlopen(self.url + "/healthz", timeout=5).read()  # noqa: S310
                return True
            except Exception:  # noqa: BLE001
                time.sleep(1)
        return False

    @property
    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def stop(self) -> None:
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()


# Tests (or another provider) can swap this factory: factory(port) -> object with start()/stop()/hostname/running.
tunnel_factory = CloudflareTunnel
