/** Tool implementations shared by stdio MCP and tests. */
import { resolve } from "node:path";
import { existsSync } from "node:fs";
import { SignError, errResult } from "./errors.js";
import { cancel, createSealedRequest, isSealed, sealedStatus, applyResponseObj } from "./sealed.js";
import { load, exists as stateExists } from "./store.js";
import type { DateFormat, Placement } from "./pdf.js";

export type RequestArgs = {
  pdf_path?: string;
  pdf_base64?: string;
  pdf_url?: string;
  output_path?: string;
  signer_name?: string;
  document_name?: string;
  placements?: Placement[];
  add_date?: boolean;
  date_format?: DateFormat;
  message?: string;
  expires_in_minutes?: number;
  delivery?: string;
  return_to?: string;
  wait_seconds?: number;
  page_base?: string;
};

async function materializePdf(args: RequestArgs): Promise<{ bytes: Uint8Array; name: string; path?: string }> {
  const path = (args.pdf_path || "").trim() || undefined;
  const b64 = (args.pdf_base64 || "").trim() || undefined;
  const url = (args.pdf_url || "").trim() || undefined;
  const n = [path, b64, url].filter(Boolean).length;
  if (n === 0) throw new SignError("Provide pdf_path, pdf_base64, or pdf_url", 400);
  if (n > 1) throw new SignError("Provide only one of pdf_path, pdf_base64, or pdf_url", 400);
  if (path) {
    const p = resolve(path);
    if (!existsSync(p)) throw new SignError(`file not found: ${path}`, 404);
    const { readFileSync } = await import("node:fs");
    return { bytes: readFileSync(p), name: args.document_name || path.split(/[/\\]/).pop() || "document.pdf", path: p };
  }
  if (b64) {
    let s = b64;
    if (s.includes(",") && s.toLowerCase().startsWith("data:")) s = s.split(",")[1];
    const data = Buffer.from(s, "base64");
    if (!data.subarray(0, 4).equals(Buffer.from("%PDF"))) {
      throw new SignError("pdf_base64 does not look like a PDF (missing %PDF header)", 400);
    }
    return { bytes: data, name: args.document_name || "document.pdf" };
  }
  const res = await fetch(url!, { headers: { "User-Agent": "gotoquill", Accept: "application/pdf,*/*" } });
  if (!res.ok) throw new SignError(`pdf_url fetch failed: HTTP ${res.status}`, 400);
  const data = Buffer.from(await res.arrayBuffer());
  if (!data.subarray(0, 4).equals(Buffer.from("%PDF"))) {
    throw new SignError("pdf_url did not return a PDF (missing %PDF header)", 400);
  }
  return { bytes: data, name: args.document_name || "document.pdf" };
}

export async function requestSignature(args: RequestArgs): Promise<Record<string, unknown>> {
  const delivery = args.delivery || "link";
  if (delivery !== "link" && delivery !== "sealed") {
    throw new SignError("TypeScript draft supports delivery='link' (sealed) for now; use Python for page/file modes", 400);
  }
  const pdf = await materializePdf(args);
  const r = await createSealedRequest({
    pdfPath: pdf.path,
    dateFormat: args.date_format,
    pdfBytes: pdf.bytes,
    documentName: pdf.name,
    signerName: args.signer_name,
    message: args.message,
    placements: args.placements,
    addDate: !!args.add_date,
    expiresInMinutes: args.expires_in_minutes,
    outputPath: args.output_path,
    returnTo: args.return_to,
    pageBase: args.page_base,
    skipPageRasters: true,
  });
  const wait = Number(args.wait_seconds || 0);
  if (wait > 0) {
    const st = await waitForSignature(String(r.request_id), wait);
    return { ...r, final_status: st, status: st.status || r.status };
  }
  return r;
}

export async function getSignatureStatus(requestId: string, waitSeconds = 0): Promise<Record<string, unknown>> {
  if (isSealed(requestId) || stateExists(requestId)) {
    return sealedStatus(requestId, waitSeconds);
  }
  throw new SignError("unknown request_id", 404);
}

export async function waitForSignature(requestId: string, waitSeconds = 600): Promise<Record<string, unknown>> {
  const wait = Math.max(0, Math.min(Number(waitSeconds || 0), 600));
  return getSignatureStatus(requestId, wait);
}

export async function cancelRequest(requestId: string): Promise<Record<string, unknown>> {
  return cancel(requestId);
}

export async function applySignatureResponse(args: {
  request_id: string;
  response_path?: string;
  response_text?: string;
  response_obj?: Record<string, unknown>;
  output_path?: string;
}): Promise<Record<string, unknown>> {
  let obj = args.response_obj;
  if (!obj && args.response_text) {
    obj = JSON.parse(args.response_text);
  }
  if (!obj && args.response_path) {
    const { readFileSync } = await import("node:fs");
    obj = JSON.parse(readFileSync(args.response_path, "utf8"));
  }
  if (!obj) throw new SignError("Provide response_obj, response_text, or response_path", 400);
  return applyResponseObj(args.request_id, obj);
}

export async function signPdf(args: RequestArgs & { timeout?: number }): Promise<Record<string, unknown>> {
  const r = await requestSignature({ ...args, wait_seconds: 0 });
  const timeout = args.timeout ?? 600;
  return waitForSignature(String(r.request_id), timeout);
}

export async function callTool(name: string, arguments_: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  try {
    switch (name) {
      case "request_signature":
        return await requestSignature(arguments_ as RequestArgs);
      case "get_signature_status":
        return await getSignatureStatus(String(arguments_.request_id), Number(arguments_.wait_seconds || 0));
      case "wait_for_signature":
        return await waitForSignature(String(arguments_.request_id), Number(arguments_.wait_seconds ?? 600));
      case "cancel_request":
        return await cancelRequest(String(arguments_.request_id));
      case "apply_signature_response":
        return await applySignatureResponse(arguments_ as Parameters<typeof applySignatureResponse>[0]);
      case "sign_pdf":
        return await signPdf(arguments_ as RequestArgs);
      case "connect_notifications":
        return {
          error: "connect_notifications is not implemented in the TypeScript draft yet; use the Python package",
          code: 501,
        };
      default:
        return { error: `unknown tool ${name}` };
    }
  } catch (e) {
    if (e instanceof SignError) return errResult(e.message, e.code);
    return errResult(String((e as Error).message || e));
  }
}

export { load as loadRequest };
