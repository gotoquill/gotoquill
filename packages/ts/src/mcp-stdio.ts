#!/usr/bin/env node
/**
 * Local stdio MCP server for gotoquill (TypeScript).
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { TOOL_ANNOTATIONS } from "./annotations.js";
import { callTool } from "./tools.js";

const INSTRUCTIONS =
  "Human confirmation required: never claim a document is signed unless the human used the signing UI (or sealed link) and explicitly consented. Do not forge signatures. gotoquill is not legal advice.\n\n" +
  "1) request_signature(pdf_path=...) returns request_id and sign_url; send sign_url to the user. " +
  "2) In the SAME turn call wait_for_signature(request_id=...) and repeat while status is pending. " +
  "3) When completed, give the user signed_pdf_path / signed_pdf_base64. Every result has a 'next' field: do exactly what it says.";

function ann(name: string) {
  return TOOL_ANNOTATIONS[name];
}

function textResult(obj: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(obj, null, 2) }] };
}

const placementSchema = z
  .object({
    kind: z.enum(["signature", "initials", "date"]).optional(),
    page: z.number().int().optional(),
    x: z.number().optional(),
    y: z.number().optional(),
    width: z.number().optional(),
    height: z.number().optional(),
    field_name: z.string().optional(),
    add_date: z.boolean().optional(),
  })
  .passthrough();

async function main() {
  const server = new McpServer({ name: "gotoquill", version: "0.1.0-draft" }, { instructions: INSTRUCTIONS });

  server.registerTool(
    "request_signature",
    {
      title: ann("request_signature")?.title,
      description:
        "Ask a human to sign a PDF. Default delivery=link returns an end-to-end encrypted sign_url. " +
        "Send the link, then wait_for_signature in the same turn until completed.",
      inputSchema: {
        pdf_path: z.string().optional().describe("Path to the PDF on this computer"),
        pdf_base64: z.string().optional().describe("PDF as base64 (cloud / remote)"),
        pdf_url: z.string().optional().describe("http(s) URL to fetch the PDF"),
        output_path: z.string().optional(),
        signer_name: z.string().optional(),
        document_name: z.string().optional(),
        placements: z.array(placementSchema).optional(),
        add_date: z.boolean().optional(),
        date_format: z.enum(["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"]).optional(),
        message: z.string().optional(),
        expires_in_minutes: z.number().int().optional(),
        delivery: z.string().optional(),
        return_to: z.string().optional(),
        wait_seconds: z.number().optional(),
      },
      annotations: ann("request_signature"),
    },
    async (args) => textResult(await callTool("request_signature", args as Record<string, unknown>)),
  );

  server.registerTool(
    "get_signature_status",
    {
      title: ann("get_signature_status")?.title,
      description: "Get status of a signature request; optional wait_seconds (max 600).",
      inputSchema: {
        request_id: z.string(),
        wait_seconds: z.number().optional(),
      },
      annotations: ann("get_signature_status"),
    },
    async (args) => textResult(await callTool("get_signature_status", args as Record<string, unknown>)),
  );

  server.registerTool(
    "wait_for_signature",
    {
      title: ann("wait_for_signature")?.title,
      description: "Block up to wait_seconds (max 600) until the request is final.",
      inputSchema: {
        request_id: z.string(),
        wait_seconds: z.number().optional(),
      },
      annotations: ann("wait_for_signature"),
    },
    async (args) => textResult(await callTool("wait_for_signature", args as Record<string, unknown>)),
  );

  server.registerTool(
    "cancel_request",
    {
      title: ann("cancel_request")?.title,
      description: "Cancel a pending signature request.",
      inputSchema: { request_id: z.string() },
      annotations: ann("cancel_request"),
    },
    async (args) => textResult(await callTool("cancel_request", args as Record<string, unknown>)),
  );

  server.registerTool(
    "apply_signature_response",
    {
      title: ann("apply_signature_response")?.title,
      description: "Apply an offline signature response JSON to a pending request.",
      inputSchema: {
        request_id: z.string(),
        response_path: z.string().optional(),
        response_text: z.string().optional(),
        output_path: z.string().optional(),
      },
      annotations: ann("apply_signature_response"),
    },
    async (args) => textResult(await callTool("apply_signature_response", args as Record<string, unknown>)),
  );

  server.registerTool(
    "sign_pdf",
    {
      title: ann("sign_pdf")?.title,
      description: "Request a signature and wait until the human finishes (or timeout).",
      inputSchema: {
        pdf_path: z.string().optional(),
        pdf_base64: z.string().optional(),
        timeout: z.number().optional(),
        signer_name: z.string().optional(),
        placements: z.array(placementSchema).optional(),
        add_date: z.boolean().optional(),
        date_format: z.enum(["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"]).optional(),
      },
      annotations: ann("sign_pdf"),
    },
    async (args) => textResult(await callTool("sign_pdf", args as Record<string, unknown>)),
  );

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
