"""Local stdio MCP server. Optional MCP Apps (io.modelcontextprotocol/ui) in-chat signing view."""
from __future__ import annotations

from typing import Any

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import Context, MCPServer as _Server
except ImportError:  # SDK 1.x
    from mcp.server.fastmcp import Context, FastMCP as _Server  # type: ignore

import json

from . import notify
from .api import sign_page_html
from .core import SignError
from .local import get_signer
from . import lenient as L
from .mcp_metadata import TOOL_ANNOTATIONS, merge_resource_meta

ELICIT_URL_CAP = "url"


def client_supports_url_elicitation(ctx: Any) -> bool:
    """True when the client advertised elicitation URL mode (capabilities.elicitation.url)."""
    try:
        caps = ctx.client_capabilities if hasattr(ctx, "client_capabilities") else ctx.session.client_params.capabilities
    except Exception:  # noqa: BLE001
        return False
    if caps is None:
        return False
    d = caps.model_dump(by_alias=True, exclude_none=True) if hasattr(caps, "model_dump") else dict(caps)
    el = d.get("elicitation")
    return isinstance(el, dict) and ELICIT_URL_CAP in el

REQUEST_DETAILS = '''request_signature options:
Ask the human to sign a local PDF.

        delivery (default "link"): returns sign_url, a one-time end-to-end encrypted link to a static signing page
        that works on any phone or computer (plus qr_png_path / qr_ascii). Only ciphertext passes through the
        relay (ntfy.sh by default). Send the link to the human, then call wait_for_signature (or
        get_signature_status(wait_seconds=600)) in the same turn, repeating until it is final;
        it fetches the encrypted reply and writes the signed PDF (default <name>.signed.pdf next to the
        original, or output_path) and an audit JSON. Expires in 60 min by default (max 180).
        delivery "page": the human is at THIS computer: a temporary page on 127.0.0.1 opens in the browser (or
        inside the chat in apps with MCP Apps support).
        delivery "link-file": like "link" but writes ONE self-contained HTML ('<name> - sign.html' or html_path)
            with the page and link params inside, to send in the chat; the signer opens it (needs internet) and the
            encrypted reply comes back via the relay; poll get_signature_status as for "link".
        delivery "file": NO internet path between you and the human: writes ONE offline HTML file
        ('<name> - sign.html', or html_path) to send them in the chat. They send back
        '<name> - signature.gotoquill' or a pasted GOTOQUILL1 code; then call apply_signature_response.

        placements: list of {"page": 1, "x": 72, "y": 650, "width": 180, "height": 60} in PDF points
        (origin top-left, 72 pt = 1 inch) or {"field_name": "Signature1"}; optional "kind":
        "signature" | "initials" | "date". Omit to auto-place: signature form fields, else labels such as
        'Signature' / 'Sign here' / 'חתימת המבוטח' / 'Firma' / 'Unterschrift' next to an empty drawn box or ruled
        line (left, right, above or below; LTR and RTL). Every detected spot is signed unless spots says otherwise
        ("all", "first", "last" or 1-based spot numbers like [1, 3]). Scanned PDFs / no label: bottom-right of the
        last page, with placement_info.guess=true.
        The result has placements, placement_info (method, guess, note) and preview_png_path(s): page images with
        the signature/date spots highlighted. SHOW THE PREVIEW to the user before sending the link. The signing
        page highlights the same spots.
        add_date: date the signature. Fills the document's own date spot (a date form field, else a 'Date'/'תאריך'
        label with a ruled line near the signature; an explicit kind "date" placement wins) and, if proof_line
        (default true), prints a small 'Signed 25 Oct 2026, 19:20 (America/New_York)' line under each signature in
        the signer's own time zone. date_format: strftime ('%d/%m/%Y') or tokens ('DD/MM/YYYY'); default follows
        the signer's browser locale (e.g. en-US 10/25/2026, he-IL/en-GB 25/10/2026), else '25 Oct 2026'.
        share_link: deprecated (Cloudflare tunnel for delivery="page"); prefer the default delivery="link".
        on_complete_command: shell command run ONCE when it finishes (status JSON on stdin; env GOTOQUILL_STATUS,
        GOTOQUILL_SIGNED_PDF, GOTOQUILL_REQUEST_ID, GOTOQUILL_PREVIEW_PNG, GOTOQUILL_NEXT).
        on_complete_webhook: URL that gets the status JSON POSTed once when it finishes.
        webhook_headers: extra headers for on_complete_webhook, e.g. {"Authorization": "env:MY_HOOK_AUTH"}; "env:VAR"
        is read when the hook fires so the secret never sits in request files. Every webhook POST also carries
        X-Gotoquill-Timestamp and X-Gotoquill-Signature (sha256=HMAC-SHA256 of "<timestamp>.<body>" with the local
        secret). webhook_body: optional JSON template with {{request_id}} {{status}} {{document_name}}
        {{signed_pdf_path}} {{next}} {{message}} or "{{status_json}}". With no hooks passed, the targets saved by
        connect_notifications / `gotoquill connect` are used automatically.
        return_to: where the signer's "Back to chat" button goes after signing, with "I signed ✅" pre-filled:
        "whatsapp[:<phone>]", "telegram[:<bot>]", "sms[:<phone>]", or an https:// / app deep link with a {text}
        placeholder (allow-listed schemes only). It travels inside the encrypted request, not in the link. Without
        it the page offers the phone's share sheet / copy. In MCP Apps hosts the in-chat view posts "I signed …"
        into the chat itself (ui/message), so the conversation continues with no extra tap.
        wait_seconds (default 0, max 600): block (async, with progress notifications) until the human finishes or
        the time passes; the result then includes final_status. Only use it if the link was already shown to the
        human some other way (e.g. the in-chat view / elicitation), since they cannot see this result until it returns.
        GETTING TOLD: after this returns, IMMEDIATELY start waiting in a way that wakes you; never end your turn
        assuming you will be told: (a) run `gotoquill wait <request_id>` as a background shell job if your host
        notifies you when it exits; (b) else call get_signature_status(wait_seconds=600) repeatedly in this turn;
        (c) or use the hooks. The server also watches the request, stamps the PDF and sends
        notifications/resources/updated for gotoquill://requests/<request_id>.
        '''

UI_URI = "ui://gotoquill/sign.html"
UI_MIME = "text/html;profile=mcp-app"
UI_EXT = "io.modelcontextprotocol/ui"

INSTRUCTIONS = (
    "Human confirmation required: never claim a document is signed unless the human used the signing UI (or sealed link) and explicitly consented. Do not forge signatures or identity documents. gotoquill / Gotoquill Cloud is not legal advice.\n\n"
    "gotoquill gets a human's signature on a local PDF. Simplest: call sign_pdf(pdf_path='/path/file.pdf') "
    "when the signer is at this computer; it opens the signing page and waits until it is signed, then returns "
    "signed_pdf_path. Otherwise: 1) request_signature(pdf_path='/path/file.pdf') returns request_id and sign_url; "
    "send sign_url to the user. 2) In the SAME turn call wait_for_signature(request_id='req_...') and repeat while "
    "status is pending. 3) When completed, give the user signed_pdf_path. Every result has a 'next' field: do "
    "exactly what it says. Details: read resource gotoquill://help."
)

HELP = (
    "gotoquill gets a human's signature on a local PDF. 1) call request_signature with pdf_path. By default it "
    "returns a one-time encrypted sign_url (and a QR code) that works on any phone or computer; send it to the user. "
    "2) IMMEDIATELY start waiting in a way that will wake you; never end your turn assuming you will be told "
    "(you only act on your own turns). In priority order: (a) if you can run background shell jobs that notify you "
    "when they exit, run `gotoquill wait <request_id>` in the background (exit 0 = signed, prints the status JSON); "
    "(b) otherwise call wait_for_signature(request_id, wait_seconds=600) (same as get_signature_status with "
    "wait_seconds=600) again and again in the same turn until the status is 'completed' (or declined/expired/"
    "cancelled); (c) or pass on_complete_command / on_complete_webhook (+ webhook_headers) "
    "to request_signature. ONE-TIME SETUP: call connect_notifications once (it auto-detects OpenClaw, or takes a "
    "webhook / Telegram target); afterwards every request_signature without hooks uses the saved targets, so you "
    "are woken when it is signed even after your turn ends. This server also watches every request itself, stamps the PDF when the reply arrives, and "
    "sends notifications/resources/updated for gotoquill://requests/<request_id> plus a log message. The signed PDF is at output_path and the audit record at audit_path. "
    "Show the user preview_png_path (where the signature goes) before sending the link, and when it is completed "
    "attach the signed PDF (signed_pdf_path) back to the signer in the chat right away, without being asked. "
    "If the user is at this computer you can use delivery='page' (local page / in-chat view); in MCP Apps hosts "
    "the in-chat view posts 'I signed …' into the chat when they sign. Pass return_to (whatsapp[:phone], "
    "telegram[:bot], sms[:phone] or an https/app link with {text}) so the phone page's 'Back to chat' button "
    "returns them to your chat with 'I signed ✅' pre-filled. "
    "NO internet path between you and the human (e.g. you run in the cloud, they are on a phone)? Use "
    "request_signature(..., delivery='file'): it writes one offline HTML file; send it to the user, they sign in any "
    "browser and send back a '.gotoquill' reply file or a code starting with GOTOQUILL1; then call "
    "apply_signature_response(request_id, response_path=... or response_text=...)."
)


def client_supports_ui(ctx: Any) -> bool:
    """True when the client advertised the MCP Apps extension."""
    try:
        caps = ctx.client_capabilities if hasattr(ctx, "client_capabilities") else ctx.session.client_params.capabilities
    except Exception:  # noqa: BLE001
        return False
    if caps is None:
        return False
    d = caps.model_dump(by_alias=True, exclude_none=True) if hasattr(caps, "model_dump") else dict(caps)
    for container in (d.get("extensions"), (d.get("experimental") or {})):
        if isinstance(container, dict) and UI_EXT in container:
            return True
    return False


def _run(fn, *a, **kw) -> dict:
    try:
        return fn(*a, **kw)
    except SignError as e:
        return _err(str(e), e.code)


def _err(msg: str, code: int = 400, next_: str | None = None) -> dict:
    if next_ is None:
        low = msg.lower()
        if code == 404 or "not found" in low or "no such file" in low or "does not exist" in low:
            next_ = ("Check the value and call again with an absolute path to an existing PDF, e.g. "
                     "request_signature(pdf_path='/home/me/contract.pdf'), or the request_id that "
                     "request_signature returned (req_ + 16 hex chars).")
        else:
            next_ = "Fix the argument named in the error and call the same tool again."
    return {"error": msg, "code": code, "next": next_}


def build_server() -> Any:
    mcp = _Server("gotoquill", instructions=INSTRUCTIONS)

    @mcp.prompt(title="Try Gotoquill", description="Create a short sample NDA and let me sign it.")
    def try_gotoquill() -> str:
        return (
            "Create a short sample NDA between my company and Dana Cohen, then let me sign it. "
            "Gotoquill has no document-generation API. If the host can generate a PDF, supply it to "
            "request_signature using pdf_path, pdf_url, or pdf_base64. Otherwise, explain the fallback "
            "and use examples/sample_contract.pdf from the Local checkout if available, with "
            "signer_name='Dana Cohen'. Resolve its absolute path before calling request_signature. "
            "If no PDF is available, ask me to attach one. Show the preview and open the returned "
            "sign_url so I can review it. The signer must review the PDF and consent in the signing UI "
            "before it is signed. Follow the tool's next guidance to wait and return the signed PDF."
        )

    @mcp.resource(UI_URI, name="gotoquill signing view", mime_type=UI_MIME,
                  description="In-chat page where the human previews the PDF and signs it",
                  meta=merge_resource_meta({"ui": {"prefersBorder": True}}))
    def sign_view() -> str:
        return sign_page_html("mcp-app")

    watching: dict[str, Any] = {}
    recent: list[str] = []  # request_ids created in this session, oldest first

    @mcp.resource("gotoquill://help", name="gotoquill full guide", mime_type="text/plain",
                  description="Full guide: delivery modes, placements, dates, hooks, return_to, file mode.")
    def help_resource() -> str:
        return HELP + "\n\n" + REQUEST_DETAILS
    creating = [0]  # request_signature calls in flight (a parallel wait_for_signature waits for them)

    @mcp.resource("gotoquill://requests/{request_id}", name="gotoquill request status", mime_type="application/json",
                  description="Live status of a signing request. Updated (notifications/resources/updated) when the "
                              "human signs, declines, or it expires.")
    def request_resource(request_id: str) -> str:
        from .tools import get_signature_status
        return json.dumps(_run(get_signature_status, request_id), default=str)

    def _start_watch(ctx: Any, rid: str) -> dict:
        """Watcher task in this long-lived server: survives the tool call returning; stamps the PDF, fires hooks
        (once) and notifies the client."""
        import asyncio

        import anyio
        if rid in watching:
            return {"mode": "mcp-server task"}
        try:
            session = ctx.session
        except Exception:  # noqa: BLE001 - called outside a live session (tests)
            session = None
        uri = f"gotoquill://requests/{rid}"

        async def run() -> None:
            try:
                st = await anyio.to_thread.run_sync(lambda: notify.poll_until_final(rid, notify._watch_timeout(rid)),
                                                    abandon_on_cancel=True)
            except Exception:  # noqa: BLE001
                return
            if st.get("status") not in notify.FINAL:
                return
            msg = {"event": "gotoquill request finished", "request_id": rid, "status": st.get("status"),
                   "signed_pdf_path": st.get("signed_pdf_path"), "resource": uri, "next": st.get("next")}
            for send in (lambda: ctx.notify_resource_updated(uri),
                         lambda: session.send_resource_updated(uri) if session else None,
                         lambda: session.send_log_message(level="notice", data=msg, logger="gotoquill") if session else None):
                try:
                    c = send()
                    if c is not None:
                        await c
                except Exception:  # noqa: BLE001 - client may be gone or not support it
                    pass

        try:
            watching[rid] = asyncio.get_running_loop().create_task(run())
        except RuntimeError:
            return notify.start_watcher(rid, "thread")
        return {"mode": "mcp-server task", "resource": uri}

    def _after_create(ctx: Any, r: dict, cmd: str | None, hook: str | None, headers: dict | None = None,
                      body: Any = None) -> dict:
        if "error" in r or "request_id" not in r:
            return r
        recent.append(r["request_id"])
        from .tools import attach_hooks
        try:
            attach_hooks(r, cmd, hook, watcher="none", webhook_headers=headers, webhook_body=body)
        except SignError as e:
            return {"error": str(e), "code": e.code}
        r.pop("watcher", None)
        from .tools import rid_sealed
        if not (rid_sealed(r["request_id"]) or r["request_id"] in get_signer().sessions):
            return r  # delivery='file': no relay to watch; hooks fire on apply_signature_response
        r["watcher"] = _start_watch(ctx, r["request_id"])
        r["resource_uri"] = f"gotoquill://requests/{r['request_id']}"
        return r

    @mcp.tool(annotations=TOOL_ANNOTATIONS["request_signature"],
             meta={"ui": {"resourceUri": UI_URI, "visibility": ["model", "app"]}, "ui/resourceUri": UI_URI})
    async def request_signature(pdf_path: str | None = None, ctx: Context = None, signer_name: str | None = None,
                          delivery: str = "link", output_path: str | None = None,
                          document_name: str | None = None, placements: list[dict] | str | None = None,
                          add_date: bool | str = False, message: str | None = None,
                          proof_line: bool | str = True, date_format: str | None = None,
                          expires_in_minutes: int | str | None = None, open_browser: bool | str | None = None,
                          share_link: bool | str = False, html_path: str | None = None,
                          spots: list[int] | str | None = None, on_complete_command: str | None = None,
                          on_complete_webhook: str | None = None, return_to: str | None = None,
                          wait_seconds: float | str | None = None, webhook_headers: dict[str, str] | str | None = None,
                          webhook_body: dict | str | None = None,
                          pdf_base64: str | None = None, pdf_url: str | None = None) -> dict:
        """Ask a human to sign a PDF. Use pdf_path locally or pdf_base64 / pdf_url remotely.
        Example: request_signature(pdf_path="/home/me/contract.pdf")
        Returns request_id and sign_url. Send sign_url to the user, then call
        wait_for_signature(request_id="req_...") in the same turn.
        delivery: "link" (default, any phone), "page" (opens a local page for a signer at this computer),
        "file" (offline HTML). If "page" opens, waits up to 120 s for signing.
        Signature spots are automatic. Full options: resource gotoquill://help.
        """
        from .returnto import normalize as _rt
        from . import cloud_io
        raw_path = pdf_path
        try:
            pdf_path = cloud_io.materialize_pdf(pdf_path=pdf_path, pdf_base64=pdf_base64, pdf_url=pdf_url,
                                                document_name=document_name)
        except SignError as e:
            return _err(str(e), e.code,
                        "Call request_signature(pdf_path='/absolute/path/file.pdf') "
                        "or pass pdf_base64 / pdf_url when running as a remote MCP.")
        pdf_path = L.norm_path(pdf_path)
        if not pdf_path:
            return _err("pdf_path is required", 400, "Call request_signature(pdf_path='/absolute/path/file.pdf').")
        if not __import__("os").path.isfile(pdf_path):
            return _err(f"PDF not found: {raw_path!r} (looked at {pdf_path})", 404)
        output_path = L.norm_path(output_path, must_exist=False)
        html_path = L.norm_path(html_path, pdf=False, must_exist=False)
        signer_name, document_name, message = L.clean_str(signer_name), L.clean_str(document_name), L.clean_str(message)
        delivery = L.norm_delivery(delivery)
        placements = L.as_json(placements) or None
        if isinstance(placements, dict):
            placements = [placements]
        if isinstance(placements, str):
            return _err("placements must be a list like [{\"page\": 1, \"x\": 72, \"y\": 650}]", 400,
                        "Omit placements (spots are auto-detected) or pass a JSON list.")
        spots = L.as_json(spots)
        if isinstance(spots, int):
            spots = [spots]
        add_date = bool(L.as_bool(add_date, False))
        proof_line = bool(L.as_bool(proof_line, True))
        share_link = bool(L.as_bool(share_link, False))
        open_browser = L.as_bool(open_browser, None)
        expires_in_minutes = L.as_int(expires_in_minutes)
        auto_wait = wait_seconds is None or wait_seconds == ""
        wait_seconds = L.as_float(wait_seconds, 0)
        webhook_headers, webhook_body = L.as_json(webhook_headers) or None, L.as_json(webhook_body) or None
        try:
            return_to = _rt(return_to)
        except SignError as e:
            return _err(str(e), e.code)
        creating[0] += 1
        try:
            r = await _request_signature(pdf_path, ctx, output_path, signer_name, document_name, placements, add_date,
                                         message, proof_line, date_format, expires_in_minutes, open_browser,
                                         share_link, delivery, html_path, spots, return_to)
            r = _after_create(ctx, r, on_complete_command, on_complete_webhook, webhook_headers, webhook_body)
        finally:
            creating[0] -= 1
        if "error" in r or "request_id" not in r:
            return r
        r["wait_tool"] = f"wait_for_signature(request_id='{r['request_id']}', wait_seconds=600)"
        if not str(r.get("delivery", "")).startswith("file"):
            r["next_call"] = {"tool": "wait_for_signature", "arguments": {"request_id": r["request_id"]}}
        if auto_wait and (r.get("browser_opened") or r.get("shown_in_chat")):
            # The signer already sees the page (local browser tab / in-chat view): wait here so weak models that
            # stop after one tool call still get the final result. GOTOQUILL_PAGE_AUTOWAIT=0 turns this off.
            import os
            from .envcompat import env_get
            wait_seconds = L.as_float(env_get("PAGE_AUTOWAIT"), 120)
            if wait_seconds > 0:
                r["auto_waited"] = True
        if wait_seconds and float(wait_seconds) > 0 and not str(r.get("delivery", "")).startswith("file"):
            st = await _wait(r["request_id"], wait_seconds, ctx)
            r["final_status"] = st
            r["status"] = st.get("status", r.get("status"))
            if st.get("next"):
                r["next"] = st["next"]
            if st.get("status") == "completed":
                r["signed_pdf_path"] = st.get("signed_pdf_path")
                r.pop("next_call", None)
        from . import cloud_io
        return cloud_io.attach_cloud_result(r)

    async def _wait(request_id: str, wait_seconds: float, ctx: Any) -> dict:
        """Async wait: the blocking poll runs in worker threads (10 s chunks) so the server keeps serving other
        requests; progress + log notifications go out every chunk so hosts don't time the call out."""
        import time

        import anyio

        from .tools import get_signature_status as _status
        wait = max(0.0, min(L.as_float(wait_seconds, 0), 600))
        given = request_id
        request_id = L.extract_request_id(request_id) or ""
        note = None
        if L.is_placeholder(request_id) and not recent:
            for _ in range(240):  # request_signature issued in parallel: let it register (max 60 s)
                if recent or (not creating[0] and _ > 8):
                    break
                await anyio.sleep(0.25)
        if L.is_placeholder(request_id) and recent:
            note = (f"request_id {given!r} is not a real id; using the latest request from this session, "
                    f"{recent[-1]}. Next time pass request_id='{recent[-1]}'.")
            request_id = recent[-1]
        elif not request_id:
            return _err("request_id is required and no request was made in this session yet", 400,
                        "First call request_signature(pdf_path='/path/file.pdf') (or sign_pdf), then call "
                        "wait_for_signature(request_id=<the request_id it returned>).")
        start = time.monotonic()
        while True:
            left = wait - (time.monotonic() - start)
            chunk = max(0.0, min(left, 10.0))
            st = await anyio.to_thread.run_sync(lambda: _run(_status, request_id, chunk), abandon_on_cancel=True)
            if "error" in st or st.get("status") in notify.FINAL or left <= 0.05:
                break
            if ctx is not None:  # keep the client informed (and the request alive) while we wait
                el = time.monotonic() - start
                try:
                    await ctx.report_progress(el, wait, message=f"waiting for the signer ({int(el)}s of {int(wait)}s)")
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await ctx.info(f"gotoquill: request {request_id} still pending after {int(el)}s")
                except Exception:  # noqa: BLE001
                    pass
        if st.get("error") and st.get("code") == 404 and not watching:
            # issued in parallel with request_signature: wait (max 60 s) for that request to register
            for _ in range(240):
                if watching or (not creating[0] and _ > 8):
                    break
                await anyio.sleep(0.25)
        if st.get("error") and st.get("code") == 404 and watching:
            # Small models often call wait_for_signature in parallel with request_signature, with a made-up id
            # ("<request_id>", "sample-request-uuid"). Point them at the real one(s) from this server.
            ids = list(watching)[-5:]
            st["recent_request_ids"] = ids
            st["next_call"] = {"tool": "wait_for_signature", "arguments": {"request_id": ids[-1]}}
            st["next"] = (f"'{request_id}' is not a request_id. Use the request_id returned by request_signature "
                          f"(looks like req_ + 16 hex chars). Requests made in this session: {', '.join(ids)}. "
                          f"Call wait_for_signature(request_id='{ids[-1]}', wait_seconds=600) now.")
        if st.get("status") == "pending":
            st["next"] = ("Still pending. Call wait_for_signature(request_id='" + request_id + "', wait_seconds=600) "
                          "(or get_signature_status with wait_seconds=600) again NOW, in this same turn, and keep "
                          "repeating until it is completed/declined/expired/cancelled (or keep `gotoquill wait "
                          + request_id + "` running in the background). Do not end your turn assuming you will be told.")
            st.setdefault("next_call", {"tool": "wait_for_signature", "arguments": {"request_id": request_id}})
        elif st.get("error") and "next" not in st:
            st["next"] = _err(st["error"], st.get("code", 400))["next"]
        if note:
            st["note"] = note
        from . import cloud_io
        return cloud_io.attach_cloud_result(st)

    async def _request_signature(pdf_path, ctx, output_path, signer_name, document_name, placements, add_date,
                                 message, proof_line, date_format, expires_in_minutes, open_browser, share_link,
                                 delivery, html_path, spots, return_to=None) -> dict:
        if delivery == "link-file":
            from . import sealed
            return _run(sealed.create_sealed_request, pdf_path=pdf_path, as_file=True, html_path=html_path,
                        output_path=output_path, signer_name=signer_name, document_name=document_name,
                        placements=placements, add_date=add_date, proof_line=proof_line, date_format=date_format, message=message,
                        expires_in_minutes=expires_in_minutes, spots=spots, return_to=return_to)
        if delivery in ("link", "sealed", None) and not share_link:
            from . import sealed
            r = _run(sealed.create_sealed_request, pdf_path=pdf_path, output_path=output_path, signer_name=signer_name,
                     document_name=document_name, placements=placements, add_date=add_date, proof_line=proof_line, date_format=date_format, message=message,
                     expires_in_minutes=expires_in_minutes, spots=spots, return_to=return_to)
            if "error" in r:
                return r
            r["shown_in_chat"] = False
            r["elicited"] = False
            if r.get("sign_url") and client_supports_url_elicitation(ctx):
                try:
                    er = await ctx.elicit_url(message="Open this one-time page to review and sign the document.",
                                              url=r["sign_url"], elicitation_id=r["request_id"])
                    r["elicited"] = getattr(er, "action", None) == "accept"
                except Exception:  # noqa: BLE001 - fall back to returning the link as text
                    pass
            return r
        if delivery == "file":
            from . import offline
            return _run(offline.create_file_request, pdf_path=pdf_path, html_path=html_path, output_path=output_path,
                        signer_name=signer_name, document_name=document_name, placements=placements,
                        add_date=add_date, proof_line=proof_line, date_format=date_format, message=message, expires_in_minutes=expires_in_minutes, spots=spots, return_to=return_to)
        if delivery not in ("page", "link", "sealed", None):
            return {"error": "delivery must be 'link', 'page' or 'file'", "code": 400}
        from .config import get_settings
        share = bool(share_link or get_settings().share_link)
        in_chat = client_supports_ui(ctx) and not share
        if open_browser is None and share:
            open_browser = False
        if open_browser is None:
            open_browser = not in_chat
        r = _run(get_signer().request, pdf_path=pdf_path, output_path=output_path, signer_name=signer_name,
                 document_name=document_name, placements=placements, add_date=add_date, proof_line=proof_line, date_format=date_format, message=message,
                 expires_in_minutes=expires_in_minutes, open_browser=open_browser, spots=spots,
                 share_link=share_link or None, return_to=return_to)
        if "error" in r:
            return r
        tip = r["next"].split("Then send the user", 1)[0] if r.get("next") else ""
        s = get_signer().sessions[r["request_id"]]
        r["sign_token"] = s.sign_token  # used by the in-chat view only
        r["shown_in_chat"] = in_chat
        if share:
            r["next"] = tip + ("Send the user this link to open on their phone or other device: " + r["sign_url"] +
                         f" (expires {r['expires_at']}; one-time; traffic passes encrypted via Cloudflare, nothing "
                         "stored there). Then " + notify.wake_guidance(r["request_id"], page=True))
            return r
        r["next"] = tip + ("Tell the user to sign " + ("in the panel above or at " if in_chat else "at ") + r["sign_url"] +
                     ". Then " + notify.wake_guidance(r["request_id"], page=True))
        return r

    @mcp.tool(annotations=TOOL_ANNOTATIONS["get_signature_status"])
    async def get_signature_status(request_id: str = "", wait_seconds: float | str = 0, ctx: Context = None) -> dict:
        """Check a signing request. Example: get_signature_status(request_id="req_0123456789abcdef")
        status: pending, completed, declined, expired or cancelled. When completed it has signed_pdf_path:
        send that file to the user. Pass wait_seconds=600 to wait. request_id defaults to the latest request."""
        return await _wait(request_id, wait_seconds, ctx)

    @mcp.tool(annotations=TOOL_ANNOTATIONS["connect_notifications"])
    async def connect_notifications(action: str = "connect", webhook_url: str | None = None,
                                    headers: dict[str, str] | None = None, body_template: dict | None = None,
                                    name: str | None = None, telegram_bot_token_env: str | None = None,
                                    chat_id: str | None = None, openclaw: bool | None = None,
                                    openclaw_config: str | None = None, openclaw_url: str | None = None,
                                    openclaw_action: str = "wake", openclaw_agent: str | None = None,
                                    yes: bool = False, test: bool = True, target_id: str | None = None) -> dict:
        """Optional one-time setup so a finished signature wakes you later. Not needed for normal signing.
        Example: connect_notifications(webhook_url="https://example.com/hook"); action: connect|status|test|remove.
        OpenClaw is auto-detected (changing an existing config needs yes=true after showing the plan)."""
        import anyio

        from .tools import connect_notifications as _c
        return await anyio.to_thread.run_sync(lambda: _c(
            action, webhook_url, headers, body_template, name, telegram_bot_token_env, chat_id, openclaw,
            openclaw_config, openclaw_url, openclaw_action, openclaw_agent, yes, test, target_id))

    @mcp.tool(annotations=TOOL_ANNOTATIONS["wait_for_signature"])
    async def wait_for_signature(request_id: str = "", wait_seconds: float | str = 600, ctx: Context = None) -> dict:
        """Wait until the human signs (up to 600 s). Call right after request_signature, in the same turn.
        Example: wait_for_signature(request_id="req_0123456789abcdef")
        request_id defaults to the latest request. If status is still pending, call it again.
        When completed, tell the user signed_pdf_path."""
        return await _wait(request_id, wait_seconds, ctx)

    @mcp.tool(annotations=TOOL_ANNOTATIONS["sign_pdf"])
    async def sign_pdf(pdf_path: str | None = None, signer_name: str | None = None, delivery: str = "page",
                       wait_seconds: float | str = 600, path: str | None = None, file_path: str | None = None,
                       pdf_base64: str | None = None, pdf_url: str | None = None,
                       ctx: Context = None) -> dict:
        """EASIEST: get a PDF signed in ONE call. Opens the signing page and waits until it is signed.
        Example: sign_pdf(pdf_path="/home/me/contract.pdf")
        Remote agents may pass pdf_base64 or pdf_url instead of pdf_path.
        Returns status and signed_pdf_path; tell the user signed_pdf_path (or signed_pdf_url over HTTP).
        delivery "page" (default) = the signer is at this computer; use "link" to get a phone link instead."""
        delivery = L.norm_delivery(delivery, "page")
        pdf_path = pdf_path or path or file_path  # common aliases weak models use
        if not (L.clean_str(pdf_path) or L.clean_str(pdf_base64) or L.clean_str(pdf_url)):
            return _err("pdf_path is required", 400,
                        "Call sign_pdf(pdf_path='/absolute/path/file.pdf') or pass pdf_base64 / pdf_url.")
        if delivery == "file":
            return _err("sign_pdf cannot wait for delivery='file'", 400,
                        "Use request_signature(pdf_path=..., delivery='file') and then apply_signature_response.")
        wait = L.as_float(wait_seconds, 600) or 600
        r = await request_signature(pdf_path=pdf_path, ctx=ctx, signer_name=signer_name, delivery=delivery,
                                    wait_seconds=0, pdf_base64=pdf_base64, pdf_url=pdf_url)
        if "error" in r:
            return r
        rid = r["request_id"]
        if delivery != "page" and not r.get("elicited"):
            # the human must see the link first; we cannot block before the model has shown it
            r["next"] = (f"Send the user this link: {r['sign_url']} . Then call "
                         f"wait_for_signature(request_id='{rid}') in this same turn.")
            return r
        st = await _wait(rid, wait, ctx)
        out = {"request_id": rid, "status": st.get("status"), "sign_url": r.get("sign_url"),
               "signed_pdf_path": st.get("signed_pdf_path"), "audit_path": st.get("audit_path"),
               "preview_png_path": r.get("preview_png_path"), "final_status": st}
        if st.get("status") == "completed":
            out["next"] = (f"Done. Tell the user the signed PDF is at {st.get('signed_pdf_path')} "
                           "(attach the file if you can).")
        elif st.get("status") == "pending":
            out["next"] = (f"Not signed yet. Tell the user to sign at {r.get('sign_url')} and call "
                           f"wait_for_signature(request_id='{rid}') now.")
            out["next_call"] = {"tool": "wait_for_signature", "arguments": {"request_id": rid}}
        else:
            out["next"] = st.get("next") or f"The request ended with status {st.get('status')}; tell the user."
        from . import cloud_io
        return cloud_io.attach_cloud_result(out)

    @mcp.tool(annotations=TOOL_ANNOTATIONS["cancel_request"])
    def cancel_request(request_id: str = "") -> dict:
        """Cancel a pending request. Example: cancel_request(request_id="req_0123456789abcdef")"""
        from . import offline
        request_id = L.extract_request_id(request_id) or ""
        if L.is_placeholder(request_id) and recent:
            request_id = recent[-1]
        if request_id not in get_signer().sessions and offline.exists(request_id):
            return _run(offline.cancel, request_id)
        return _run(get_signer().cancel, request_id)

    @mcp.tool(annotations=TOOL_ANNOTATIONS["apply_signature_response"])
    def apply_signature_response(request_id: str, response_path: str | None = None, response_text: str | None = None,
                                 output_path: str | None = None) -> dict:
        """Finish a delivery='file' request with the human's reply.
        Example: apply_signature_response(request_id="req_...", response_text="GOTOQUILL1...")
        or response_path="/path/x.gotoquill". Writes the signed PDF + audit JSON."""
        from . import offline
        request_id = L.extract_request_id(request_id) or ""
        if L.is_placeholder(request_id) and recent:
            request_id = recent[-1]
        response_path = L.norm_path(response_path, pdf=False)
        output_path = L.norm_path(output_path, must_exist=False)
        response_text = L.clean_str(response_text)
        return _run(offline.apply_signature_response, request_id, response_path=response_path,
                    response_text=response_text, output_path=output_path)

    # ---- app-only tools used by the in-chat view (hidden from the model by MCP Apps hosts) ----
    app_only = {"ui": {"resourceUri": UI_URI, "visibility": ["app"]}}

    @mcp.tool(annotations=TOOL_ANNOTATIONS["ui_load_document"], meta=app_only)
    def ui_load_document(sign_token: str) -> dict:
        """(In-chat view only) Load the document preview for a signing request."""
        return _run(get_signer().ui_view, sign_token)

    @mcp.tool(annotations=TOOL_ANNOTATIONS["ui_submit_signature"], meta=app_only)
    def ui_submit_signature(sign_token: str, decision: str, signature_png_base64: str | None = None,
                            method: str | None = None, typed_name: str | None = None,
                            signer_name: str | None = None, consent: bool = False,
                            decline_reason: str | None = None, use_saved: str | None = None,
                            save_as: str | None = None, vault_nonce: str | None = None,
                            signer_timezone: str | None = None, signer_utc_offset: int | None = None,
                            signer_locale: str | None = None, signed_by_line: bool = False) -> dict:
        """(In-chat view only) Submit the human's signature or decline. Saved signatures need the page's
        one-time vault_nonce, which only the human's view receives."""
        return _run(get_signer().ui_submit, sign_token, decision=decision, signature_png_base64=signature_png_base64,
                    method=method, typed_name=typed_name, signer_name=signer_name, consent=consent,
                    decline_reason=decline_reason, use_saved=use_saved, save_as=save_as, vault_nonce=vault_nonce,
                    signer_timezone=signer_timezone, signer_utc_offset=signer_utc_offset, signer_locale=signer_locale,
                    signed_by_line=bool(signed_by_line))

    @mcp.tool(annotations=TOOL_ANNOTATIONS["ui_delete_saved_signature"], meta=app_only)
    def ui_delete_saved_signature(sign_token: str, vault_nonce: str, name: str | None = None) -> dict:
        """(In-chat view only) Delete a saved signature when the human clicks Delete. Returns no images."""
        r = _run(get_signer().ui_delete_saved, sign_token, vault_nonce, name)
        if "saved_signatures" in r:
            r["saved_signatures"] = [{k: v for k, v in x.items() if k != "image"} for x in r["saved_signatures"]]
        return r

    return mcp
