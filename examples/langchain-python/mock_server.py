"""Local MCP fixture. No PDF, network, signature, credential, or human impersonation."""
from fastmcp import FastMCP

server = FastMCP("Gotoquill example fixture")
checks = 0


@server.tool()
def request_signature(signer_name: str = "Dana Cohen") -> dict:
    """Return a pending fixture for browser consent handoff."""
    global checks
    checks = 0
    return {"request_id": "fixture-dana", "status": "pending", "sign_url": "https://signing.invalid/review"}


@server.tool()
def get_signature_status(request_id: str) -> dict:
    """Remain pending once, then simulate a decline, never a signature."""
    global checks
    checks += 1
    return {"request_id": request_id, "status": "pending" if checks == 1 else "declined"}


if __name__ == "__main__":
    server.run(transport="stdio", show_banner=False)
