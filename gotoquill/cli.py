"""Command line: `gotoquill mcp` (local stdio MCP server, the default) and `gotoquill sign file.pdf`."""
from __future__ import annotations

import argparse
import json
import sys


def _hdrs(a) -> dict | None:
    out = {}
    for kv in getattr(a, "webhook_header", None) or []:
        k, sep, v = kv.partition("=")
        if not sep:
            print(f"error: --webhook-header needs K=V, got {kv!r}", file=sys.stderr)
            sys.exit(2)
        out[k.strip()] = v.strip()
    return out or None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="gotoquill", description="Get a human signature on a local PDF.")
    sub = ap.add_subparsers(dest="cmd")
    mcp_p = sub.add_parser("mcp", help="run the MCP server (stdio by default; --http for remote)")
    mcp_p.add_argument("--http", action="store_true",
                       help="serve Streamable HTTP MCP at /mcp (for ChatGPT/Claude/Muse via a tunnel)")
    mcp_p.add_argument("--host", default="127.0.0.1", help="HTTP bind host (default 127.0.0.1)")
    mcp_p.add_argument("--port", type=int, default=8787, help="HTTP port (default 8787)")
    mcp_p.add_argument("--public-url", default=None,
                       help="public base URL when already behind a tunnel (sets download link host)")
    tun = sub.add_parser("tunnel", help="run HTTP MCP + Cloudflare quick tunnel; print public MCP URL")
    tun.add_argument("--host", default="127.0.0.1")
    tun.add_argument("--port", type=int, default=8787)
    s = sub.add_parser("sign", help="open a signing page for a PDF and wait")
    s.add_argument("pdf")
    s.add_argument("-o", "--output", help="signed PDF path (default: <name>.signed.pdf)")
    s.add_argument("--signer-name")
    s.add_argument("--message")
    s.add_argument("--add-date", action="store_true")
    s.add_argument("--no-proof-line", dest="proof_line", action="store_false")
    s.add_argument("--date-format")
    s.add_argument("--share-link", action="store_true", default=None,
                   help=argparse.SUPPRESS)  # deprecated Cloudflare tunnel; use --link
    s.add_argument("--link", action="store_true",
                   help="sealed link: print a one-time encrypted link + QR code to sign on any phone, then wait")
    s.add_argument("--link-file", action="store_true",
                   help="sealed file: write one self-contained '<name> - sign.html' (encrypted relay flow), then wait")
    s.add_argument("--expires", type=int, default=None, help="minutes until the request expires (sealed: max 180)")
    s.add_argument("--no-wait", action="store_true", help="(--link/--link-file) create the request and exit")
    s.add_argument("--on-complete-command", help="shell command run once when it is signed/declined/expired "
                   "(status JSON on stdin; env GOTOQUILL_STATUS, GOTOQUILL_SIGNED_PDF, GOTOQUILL_REQUEST_ID, ...)")
    s.add_argument("--return-to", help="signer's 'Back to chat' target: whatsapp[:PHONE], telegram[:BOT], "
                   "sms[:PHONE] or an https/app link with {text}")
    s.add_argument("--on-complete-webhook", help="URL that gets the status JSON POSTed once when it finishes")
    s.add_argument("--webhook-header", action="append", metavar="K=V", help="extra webhook header; K=env:VAR reads "
                   "the env var when it fires (repeatable)")
    s.add_argument("--webhook-body", metavar="JSON", help="webhook body template ({{status}}, {{signed_pdf_path}}, "
                   "{{message}}, \"{{status_json}}\" ...)")
    c = sub.add_parser("connect", help="one-time setup: save notify targets that wake your agent when a request "
                       "finishes (OpenClaw auto-detected, any webhook, Telegram); test-pings them")
    c.add_argument("--webhook", metavar="URL", help="n8n / Zapier / Make / LangGraph / your own endpoint")
    c.add_argument("--header", action="append", metavar="K=V", help="webhook header stored in the local encrypted "
                   "store (repeatable)")
    c.add_argument("--header-env", action="append", metavar="K=ENVVAR", help="webhook header read from ENVVAR at "
                   "send time; the secret never touches disk (repeatable)")
    c.add_argument("--body-template", metavar="JSON", help="webhook body template")
    c.add_argument("--name", help="target id (default: webhook / telegram)")
    c.add_argument("--telegram-bot-token-env", metavar="VAR", help="env var that holds the Telegram bot token")
    c.add_argument("--chat-id", help="Telegram chat id (or @channel)")
    c.add_argument("--openclaw", action="store_true", default=None, help="set up OpenClaw hooks (auto when detected)")
    c.add_argument("--no-openclaw", dest="openclaw", action="store_false")
    c.add_argument("--openclaw-config", metavar="PATH", help="openclaw.json (default: $OPENCLAW_CONFIG_PATH or "
                   "~/.openclaw/openclaw.json)")
    c.add_argument("--openclaw-url", metavar="URL", help="hook URL (default http://127.0.0.1:<gateway port>/hooks/gotoquill)")
    c.add_argument("--openclaw-action", choices=["wake", "agent"], default="wake",
                   help="wake: system event in the main session (default); agent: persistent 'hook:gotoquill' session")
    c.add_argument("--openclaw-agent", metavar="ID", help="OpenClaw agent id for the mapping")
    c.add_argument("--yes", action="store_true", help="apply changes to an existing host config (a backup is made)")
    c.add_argument("--no-test", dest="test", action="store_false", help="skip the test ping")
    c.add_argument("--test", dest="test_only", action="store_true", help="only test-ping the saved targets")
    c.add_argument("--status", action="store_true", help="list saved targets (secrets masked)")
    c.add_argument("--remove", nargs="?", const="all", metavar="ID", help="remove one target, or all (default)")
    w = sub.add_parser("wait", help="block until a request is completed/declined/expired/cancelled; print the "
                       "status JSON; exit 0 completed, 3 declined, 4 expired, 5 cancelled, 6 timeout, 2 error. "
                       "Run it as a background job so your host wakes you when it exits.")
    w.add_argument("request_id")
    w.add_argument("--timeout", type=float, default=None, help="seconds (default: until the request expires)")
    wt = sub.add_parser("_watch", help=argparse.SUPPRESS)
    wt.add_argument("request_id")
    st = sub.add_parser("status", help="status of a request; --wait N seconds pulls the sealed reply and stamps the PDF")
    st.add_argument("request_id")
    st.add_argument("--wait", type=float, default=0)
    s.add_argument("--file-mode", action="store_true",
                   help="no connection: write one offline '<name> - sign.html' to send to the signer, then exit")
    s.add_argument("--html", help="where to write the offline HTML (with --file-mode)")
    ap_apply = sub.add_parser("apply", help="apply a signature reply (file or pasted code) to a --file-mode request")
    ap_apply.add_argument("request_id")
    ap_apply.add_argument("response", help="path to the .gotoquill file, or the GOTOQUILL1 code itself")
    ap_apply.add_argument("-o", "--output")
    s.add_argument("--no-browser", action="store_true", help="just print the URL")
    s.add_argument("--timeout", type=float, default=None, help="seconds to wait (default: until the page expires)")
    sg = sub.add_parser("signature", help="saved signature on this computer: show (path/metadata only) or delete")
    sg.add_argument("action", choices=["show", "delete"])
    sg.add_argument("--name", choices=["signature", "initials"], help="only this one (default: all)")
    a = ap.parse_args(argv)

    if a.cmd == "connect":
        from . import connect as C
        from . import targets as T
        try:
            if a.status:
                out = T.status()
            elif a.remove:
                out = {"removed": T.remove(a.remove)}
            elif a.test_only:
                out = C.run_tests()
            else:
                out = C.connect(webhook=a.webhook, headers=C.parse_headers(a.header, a.header_env),
                                body=a.body_template, name=a.name, telegram_bot_token_env=a.telegram_bot_token_env,
                                chat_id=a.chat_id, openclaw=a.openclaw, openclaw_config=a.openclaw_config,
                                openclaw_url_=a.openclaw_url, openclaw_action=a.openclaw_action,
                                openclaw_agent=a.openclaw_agent, yes=a.yes, test=a.test)
        except T.TargetError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(2)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        if (out.get("openclaw") or {}).get("needs_confirmation"):
            sys.exit(1)
        sys.exit(0 if out.get("ok", True) else 3)

    if a.cmd == "signature":
        from . import vault
        if a.action == "show":
            info = vault.info()
            if a.name:
                info["signatures"] = [x for x in info["signatures"] if x["name"] == a.name]
            print(json.dumps(info, indent=2))
        else:
            removed = vault.delete(a.name)
            print("deleted: " + (", ".join(removed) if removed else "nothing (no saved signature)"))
        return

    if a.cmd == "apply":
        from pathlib import Path

        from . import offline
        from .core import SignError
        is_file = not a.response.strip().startswith(offline.CODE_PREFIX) and Path(a.response).expanduser().is_file()
        try:
            res = offline.apply_signature_response(a.request_id, response_path=a.response if is_file else None,
                                                   response_text=None if is_file else a.response, output_path=a.output)
        except SignError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(2)
        print(json.dumps({k: v for k, v in res.items() if k != "audit"}, indent=2))
        sys.exit(0 if res["status"] == "completed" else 1)

    if a.cmd == "sign" and a.file_mode:
        from . import offline
        from .core import SignError
        try:
            r = offline.create_file_request(pdf_path=a.pdf, html_path=a.html, output_path=a.output,
                                            signer_name=a.signer_name, message=a.message, add_date=a.add_date, proof_line=a.proof_line, date_format=a.date_format, return_to=a.return_to)
        except SignError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(2)
        print(f"Send this file to the signer: {r['html_path']}", file=sys.stderr)
        print(f"Then run: gotoquill apply {r['request_id']} <reply file or code>", file=sys.stderr)
        print(json.dumps({k: v for k, v in r.items() if k != "next"}, indent=2))
        return

    if a.cmd in ("wait", "_watch"):
        from . import notify
        from .core import SignError
        try:
            timeout = a.timeout if a.cmd == "wait" and a.timeout is not None else notify._watch_timeout(a.request_id)
            st = notify.poll_until_final(a.request_id, timeout)
        except SignError as e:
            print(json.dumps({"request_id": a.request_id, "status": "error", "error": str(e)}), flush=True)
            sys.exit(2)
        except KeyboardInterrupt:
            sys.exit(130)
        out = {k: v for k, v in st.items() if k != "audit"}
        if out.get("status") not in notify.FINAL:
            out["timed_out"] = True
            out["next"] = (f"Still pending. Run `gotoquill wait {a.request_id}` again (in the background) to keep "
                           "waiting; do not end your turn assuming you will be told.")
        print(json.dumps(out, indent=2), flush=True)
        sys.exit(notify.EXIT_CODES.get(out.get("status") if not out.get("timed_out") else "timeout", 1))

    if a.cmd == "status":
        from .core import SignError
        from .tools import get_signature_status
        try:
            print(json.dumps(get_signature_status(a.request_id, wait_seconds=a.wait), indent=2))
        except SignError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(2)
        return

    if a.cmd == "sign" and (a.link or a.link_file):
        from . import sealed
        from .core import SignError
        try:
            r = sealed.create_sealed_request(pdf_path=a.pdf, output_path=a.output, signer_name=a.signer_name,
                                             message=a.message, add_date=a.add_date, proof_line=a.proof_line, date_format=a.date_format, expires_in_minutes=a.expires,
                                             as_file=a.link_file, html_path=a.html if a.link_file else None,
                                             return_to=a.return_to)
        except SignError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(2)
        from .tools import attach_hooks
        try:
            attach_hooks(r, a.on_complete_command, a.on_complete_webhook, "process" if a.no_wait else "none",
                         webhook_headers=_hdrs(a), webhook_body=a.webhook_body)
        except SignError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(2)
        if r.get("link_fallback"):
            print(f"warning: {r['warning']}", file=sys.stderr)
        if a.link_file or r.get("link_fallback"):
            print(f"Send this file to the signer (it holds the key): {r['html_path']}\n"
                  f"request_id={r['request_id']} expires {r['expires_at']}", file=sys.stderr, flush=True)
        else:
            print((r.get("qr_ascii") or "") + f"\nSign here (one-time, expires {r['expires_at']}):\n{r['sign_url']}",
                  file=sys.stderr, flush=True)
        if a.no_wait:
            print(json.dumps({k: v for k, v in r.items() if k not in ("next", "qr_ascii")}, indent=2))
            print(f"Run `gotoquill wait {r['request_id']}` in the background to be told when it is signed.",
                  file=sys.stderr)
            return
        from . import notify
        try:
            res = notify.poll_until_final(r["request_id"], a.timeout if a.timeout is not None else 3 * 3600)
        except KeyboardInterrupt:
            res = sealed.cancel(r["request_id"])
        print(json.dumps(res, indent=2))
        sys.exit(0 if res["status"] == "completed" else 1)

    if a.cmd == "sign":
        from .core import SignError
        from .local import get_signer
        signer = get_signer()
        try:
            r = signer.request(pdf_path=a.pdf, output_path=a.output, signer_name=a.signer_name, message=a.message,
                               add_date=a.add_date, proof_line=a.proof_line, date_format=a.date_format, open_browser=False if a.no_browser else None,
                               share_link=a.share_link, return_to=a.return_to)
        except SignError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(2)
        from .tools import attach_hooks
        try:
            attach_hooks(r, a.on_complete_command, a.on_complete_webhook, webhook_headers=_hdrs(a), webhook_body=a.webhook_body)
        except SignError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(2)
        print(f"Sign here: {r['sign_url']}", file=sys.stderr, flush=True)
        try:
            res = signer.wait(r["request_id"], a.timeout)
        except KeyboardInterrupt:
            res = signer.cancel(r["request_id"])
        res = signer.status(r["request_id"])  # fires completion hooks (once)
        signer.shutdown()
        print(json.dumps({k: v for k, v in res.items() if k != "audit"}, indent=2))
        sys.exit(0 if res["status"] == "completed" else 1)

    if a.cmd == "tunnel":
        from .mcp_http import run_tunnel
        run_tunnel(host=a.host, port=a.port)
        return

    if a.cmd == "mcp" and getattr(a, "http", False):
        from .mcp_http import run_http
        run_http(host=a.host, port=a.port, public_url=a.public_url)
        return

    from .mcp_server import build_server
    build_server().run("stdio")


if __name__ == "__main__":
    main(sys.argv[1:])
