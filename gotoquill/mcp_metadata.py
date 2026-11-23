"""MCP tool annotations and resource metadata used by the Local server."""
from __future__ import annotations

from typing import Any

try:
    from mcp.types import ToolAnnotations
except ImportError:  # pragma: no cover
    ToolAnnotations = None  # type: ignore


def tool_annotations(
    *,
    title: str | None = None,
    read_only: bool = False,
    destructive: bool = False,
    open_world: bool = False,
    idempotent: bool | None = None,
) -> Any:
    """Build ToolAnnotations. Idempotent defaults to read_only when unset."""
    if ToolAnnotations is None:
        return {
            "title": title,
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
            "openWorldHint": open_world,
            "idempotentHint": read_only if idempotent is None else idempotent,
        }
    return ToolAnnotations(
        title=title,
        readOnlyHint=read_only,
        destructiveHint=destructive,
        openWorldHint=open_world,
        idempotentHint=read_only if idempotent is None else idempotent,
    )


# Tool hints advertised by the Local MCP server.
TOOL_ANNOTATIONS: dict[str, Any] = {
    "request_signature": tool_annotations(
        title="Request a human signature",
        read_only=False,
        destructive=False,
        open_world=True,  # may fetch a remote PDF or contact a relay
    ),
    "sign_pdf": tool_annotations(
        title="Sign a PDF (request + wait)",
        read_only=False,
        destructive=False,
        open_world=True,
    ),
    "get_signature_status": tool_annotations(
        title="Get signature request status",
        read_only=True,
        destructive=False,
        open_world=False,
    ),
    "wait_for_signature": tool_annotations(
        title="Wait for human to sign",
        read_only=False,  # may stamp PDF when complete
        destructive=False,
        open_world=False,
    ),
    "connect_notifications": tool_annotations(
        title="Connect completion notifications",
        read_only=False,
        destructive=False,
        open_world=True,
    ),
    "cancel_request": tool_annotations(
        title="Cancel a signature request",
        read_only=False,
        destructive=True,
        open_world=False,
    ),
    "apply_signature_response": tool_annotations(
        title="Apply offline signature response",
        read_only=False,
        destructive=False,
        open_world=False,
    ),
    "ui_load_document": tool_annotations(
        title="Load document for in-chat signing UI",
        read_only=True,
        destructive=False,
        open_world=False,
    ),
    "ui_submit_signature": tool_annotations(
        title="Submit human signature or decline",
        read_only=False,
        destructive=True,  # irreversible stamp / decline
        open_world=False,
    ),
    "ui_delete_saved_signature": tool_annotations(
        title="Delete a saved signature",
        read_only=False,
        destructive=True,
        open_world=False,
    ),
}


def merge_resource_meta(base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Preserve the existing Local UI metadata without a hosted-package import."""
    from .envcompat import env_get

    public_base = (env_get("CLOUD_PUBLIC_BASE") or env_get("PUBLIC_BASE")
                   or "https://mcp.gotoquill.com").rstrip("/")
    widget = (env_get("CLOUD_WIDGET_DOMAIN") or "").strip() or public_base
    domains = [public_base]
    out = dict(base or {})
    ui = dict(out.get("ui") or {})
    ui.update(prefersBorder=True, domain=widget,
              csp={"connectDomains": domains, "resourceDomains": list(domains)})
    out["ui"] = ui
    out["openai/widgetCSP"] = {"connect_domains": list(domains), "resource_domains": list(domains)}
    return out
