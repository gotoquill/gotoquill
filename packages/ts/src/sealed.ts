/** Sealed-link create / poll / apply. Wire-compatible with Python sealed + offline. */
import { createHash, randomBytes } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { mkdirSync, writeFileSync } from "node:fs";
import { aad, b64u, b64uDecode, hmacSha256Hex, newKey, newRequestId, newTopic, proofMessage, safeEqualHex, seal, unseal } from "./crypto.js";
import { SignError } from "./errors.js";
import {
  DATE_FORMATS,
  type DateFormat,
  defaultPlacements,
  inspectPdf,
  placeholderPngBase64,
  sha256,
  stampPdf,
  type Placement,
  type SignerCtx,
} from "./pdf.js";
import { getRelay, pageUrl, RelayError, setRelay, type Relay } from "./relay.js";
import {
  DEFAULT_CONSENT,
  exists as stateExists,
  friendlyName,
  load,
  readOriginal,
  store,
  writeOriginal,
  type RequestState,
} from "./store.js";

export const DELIVERY = "sealed link via relay";
export const DEFAULT_TTL_MINUTES = 60;
export const MAX_TTL_MINUTES = 180;
export const RESPONSE_TYPES = new Set(["gotoquill-response", "agent-sign-response"]);

function iso(d: Date): string {
  return d.toISOString().replace(/\.\d{3}Z$/, "Z");
}

function buildLink(page: string, reqTopic: string, replyTopic: string, key: Buffer, relayBase: string, kind: string): string {
  let frag = `v=1&q=${reqTopic}&a=${replyTopic}&k=${b64u(key)}`;
  const defaultNtfy = "https://ntfy.sh";
  if (relayBase.replace(/\/$/, "") !== defaultNtfy) {
    frag += "&r=" + encodeURIComponent(relayBase);
  }
  if (kind === "gotoquill") frag += "&rt=gotoquill";
  return page.split("#")[0] + "#" + frag;
}

export type CreateSealedOpts = {
  pdfPath?: string;
  pdfBytes?: Uint8Array;
  documentName?: string;
  signerName?: string;
  message?: string;
  placements?: Placement[];
  addDate?: boolean;
  dateFormat?: DateFormat;
  expiresInMinutes?: number;
  outputPath?: string;
  returnTo?: string | null;
  pageBase?: string;
  relay?: Relay;
  /** When true, omit real page rasters (Workers / no pdfium). Signing page should use pdf_base64. */
  skipPageRasters?: boolean;
};

export async function createSealedRequest(opts: CreateSealedOpts): Promise<Record<string, unknown>> {
  if (opts.relay) setRelay(opts.relay);
  const r = getRelay();
  let pdfBytes: Buffer;
  let docName: string;
  if (opts.pdfBytes) {
    pdfBytes = Buffer.from(opts.pdfBytes);
    docName = opts.documentName || "document.pdf";
  } else if (opts.pdfPath) {
    const { readFileSync } = await import("node:fs");
    pdfBytes = readFileSync(resolve(opts.pdfPath));
    docName = opts.documentName || opts.pdfPath.split(/[/\\]/).pop() || "document.pdf";
  } else {
    throw new SignError("Provide pdf_path or pdfBytes", 400);
  }
  if (pdfBytes.length > 8 * 1024 * 1024) throw new SignError("PDF too large", 413);

  const info = await inspectPdf(pdfBytes);
  const placements =
    opts.placements && opts.placements.length
      ? opts.placements.map((p) => ({ ...p, kind: p.kind || ("signature" as const) }))
      : defaultPlacements(info.page_count, info.page_sizes);
  if (opts.addDate) {
    for (const p of placements) {
      if (p.kind !== "date") {
        p.add_date = true;
        p.proof_line = true;
      }
    }
  }

  if (opts.dateFormat != null && !DATE_FORMATS.includes(opts.dateFormat)) throw new SignError("invalid date_format");
  for (const p of placements) if (opts.dateFormat && !p.date_format) p.date_format = opts.dateFormat;
  const ttl = opts.expiresInMinutes ?? DEFAULT_TTL_MINUTES;
  if (ttl < 1 || ttl > MAX_TTL_MINUTES) throw new SignError(`expires_in_minutes must be 1..${MAX_TTL_MINUTES}`);

  const rid = newRequestId();
  const hmacKey = randomBytes(32);
  const aesKey = newKey();
  const reqTopic = newTopic();
  const replyTopic = newTopic();
  const now = new Date();
  const expires = new Date(now.getTime() + ttl * 60_000);
  const nice = friendlyName(docName);
  const outPath =
    opts.outputPath ||
    (opts.pdfPath ? opts.pdfPath.replace(/\.pdf$/i, "") + " - signed.pdf" : `${nice} - signed.pdf`);
  const auditPath = outPath.replace(/\.pdf$/i, "") + ".audit.json";

  const pages = opts.skipPageRasters
    ? Array.from({ length: info.page_count }, () => placeholderPngBase64())
    : Array.from({ length: info.page_count }, () => placeholderPngBase64()); // full raster needs pdfium; placeholder for TS draft

  const boxes = placements.map((p, i) => {
    const page = p.page || 1;
    const size = info.page_sizes[page - 1] || [612, 792];
    const w = p.width ?? 180;
    const h = p.height ?? w / 3;
    return {
      i,
      page,
      // normalized 0..1 for signing page overlay (top-left origin)
      x: (p.x ?? 72) / size[0],
      y: (p.y ?? 72) / size[1],
      w: w / size[0],
      h: h / size[1],
      kind: p.kind || "signature",
      date_format: p.date_format,
    };
  });

  const pageData = {
    request_id: rid,
    document_name: docName,
    signer_name: opts.signerName || null,
    message: opts.message || null,
    page_count: info.page_count,
    original_sha256: sha256(pdfBytes),
    consent_text: DEFAULT_CONSENT,
    created_at: iso(now),
    expires_at: iso(expires),
    return_to: opts.returnTo || null,
    key: hmacKey.toString("hex"),
    response_name: `${nice} - signature`,
    boxes,
    version: 1,
  };

  const payload: Record<string, unknown> = {
    type: "gotoquill-sealed-request",
    version: 1,
    data: pageData,
    pages,
    placements,
    pdf_base64: pdfBytes.toString("base64"),
    document_sha256: pageData.original_sha256,
  };

  let blob = seal(aesKey, Buffer.from(JSON.stringify(payload)), aad("request", reqTopic));
  if (blob.length > 1 * 1024 * 1024) {
    payload.pdf_base64 = null;
    blob = seal(aesKey, Buffer.from(JSON.stringify(payload)), aad("request", reqTopic));
  }
  try {
    await r.publish(reqTopic, blob, "request.bin");
  } catch (e) {
    throw new SignError(`could not upload to the relay: ${(e as Error).message}. Try a smaller PDF.`, 502);
  }

  const pageBase = opts.pageBase || pageUrl();
  const link = buildLink(pageBase, reqTopic, replyTopic, aesKey, r.base_url, r.kind);

  const state: RequestState = {
    request_id: rid,
    status: "pending",
    delivery: DELIVERY,
    created_at: pageData.created_at,
    expires_at: pageData.expires_at,
    document_name: docName,
    friendly_name: nice,
    signer_name: opts.signerName || null,
    message: opts.message || null,
    placements,
    page_count: info.page_count,
    original_sha256: pageData.original_sha256,
    consent_text: DEFAULT_CONSENT,
    key: hmacKey.toString("hex"),
    pdf_path: opts.pdfPath,
    output_path: outPath,
    audit_path: auditPath,
    return_to: opts.returnTo || null,
    sealed: {
      relay: r.base_url,
      relay_type: r.kind,
      request_topic: reqTopic,
      reply_topic: replyTopic,
      key: b64u(aesKey),
      payload_bytes: blob.length,
    },
    sign_url: link,
    placement_info: opts.placements?.length ? { method: "explicit", guess: false } : { method: "fallback", guess: true },
    pdf_base64: pdfBytes.toString("base64"),
  };

  store(state);
  writeOriginal(rid, pdfBytes);

  return {
    request_id: rid,
    status: "pending",
    delivery: DELIVERY,
    sign_url: link,
    expires_at: state.expires_at,
    document_sha256: state.original_sha256,
    output_path: outPath,
    audit_path: auditPath,
    placements,
    placement_info: state.placement_info,
    wait_tool: `wait_for_signature(request_id='${rid}', wait_seconds=600)`,
    next:
      `Send the user this link (or show the QR code). It opens a signing page on any phone or computer: ${link}  ` +
      `It works once and expires ${state.expires_at}. Only encrypted data passes through the relay (${r.base_url}). ` +
      `Then call wait_for_signature(request_id='${rid}', wait_seconds=600) in this same turn until it is final.`,
  };
}

function aesKeyFromState(d: RequestState): Buffer {
  const k = d.sealed?.key;
  if (!k) throw new SignError("sealed key already consumed", 409);
  return b64uDecode(k);
}

export async function applyResponseObj(requestId: string, resp: Record<string, unknown>): Promise<Record<string, unknown>> {
  const d = load(requestId);
  if (resp.request_id !== requestId) {
    throw new SignError(`this signature response is for a different request (${resp.request_id}), not ${requestId}`, 409);
  }
  if (d.status === "completed") {
    throw new SignError("this request was already signed and applied; a response can be used only once", 409);
  }
  if (d.status !== "pending") throw new SignError(`cannot apply: request is ${d.status}`, 409);
  const now = new Date();
  if (new Date(d.expires_at).getTime() < now.getTime()) {
    d.status = "expired";
    store(d);
    throw new SignError("this request has expired; create a new one", 410);
  }
  if (resp.original_sha256 !== d.original_sha256) {
    throw new SignError("document hash does not match this request", 409);
  }
  if (resp.decision === "decline") {
    d.status = "declined";
    d.decline_reason = String(resp.decline_reason || "").slice(0, 500) || null;
    store(d);
    return { request_id: requestId, status: "declined", decline_reason: d.decline_reason };
  }
  if (resp.decision !== "sign") throw new SignError("decision must be 'sign' or 'decline'");
  if (resp.consent !== true || resp.consent_text !== d.consent_text) {
    throw new SignError("consent is missing or does not match", 400);
  }

  let pngB64 = String(resp.signature_png || "");
  if (pngB64.includes(",")) pngB64 = pngB64.split(",")[1];
  const png = Buffer.from(pngB64, "base64");
  if (png.length < 8 || png[0] !== 0x89) throw new SignError("signature_png is not a PNG", 400);
  const sigSha = createHash("sha256").update(png).digest("hex");
  const method = resp.method === "typed" ? "typed" : "drawn";
  const typed = String(resp.typed_name || "").slice(0, 200);
  const name = String(resp.signer_name || "").slice(0, 200);
  const cts = String(resp.client_timestamp || "").slice(0, 40);
  const msg = proofMessage(requestId, d.original_sha256, sigSha, method, typed, name, cts);
  const keyB = Buffer.from(d.key, "hex");
  const good = hmacSha256Hex(keyB, msg);
  const legacyMsg = ["agent-sign/v1", requestId, d.original_sha256, sigSha, method, typed, name, cts].join("|");
  const goodLegacy = hmacSha256Hex(keyB, legacyMsg);
  const got = String(resp.proof || "");
  if (!(safeEqualHex(good, got) || safeEqualHex(goodLegacy, got))) {
    throw new SignError("proof check failed: the response was changed or made for another request", 403);
  }

  let signedAt = now;
  try {
    const ct = new Date(cts);
    if (!Number.isNaN(ct.getTime())) signedAt = ct;
  } catch {
    /* ignore */
  }

  const original = stateExists(requestId) ? readOriginal(requestId) : Buffer.from(d.pdf_base64 || "", "base64");
  const signer = name || typed || d.signer_name || null;
  const sctx: SignerCtx = {
    date_format: resp.date_format as string | undefined,
    date_text: resp.date_text as string | undefined,
    timezone: (resp.signer_timezone as string) || null,
    utc_offset_minutes: typeof resp.signer_utc_offset === "number" ? resp.signer_utc_offset : null,
    locale: (resp.signer_locale as string) || null,
  };
  const outBytes = await stampPdf({
    pdfBytes: original,
    placements: d.placements,
    signaturePng: png,
    signedAt,
    signerName: signer,
    requestId,
    signer: sctx,
    signedByLine: resp.signed_by_line === true,
  });

  const outPath = d.output_path || `${d.friendly_name || "Document"} - signed.pdf`;
  const auditPath = d.audit_path || outPath.replace(/\.pdf$/i, "") + ".audit.json";
  try {
    mkdirSync(dirname(resolve(outPath)), { recursive: true });
    writeFileSync(outPath, outBytes);
  } catch {
    /* Cloud may not write filesystem; still return base64 */
  }
  const audit = {
    request_id: requestId,
    document_name: d.document_name,
    signer_name: signer,
    signed_at: iso(signedAt),
    delivery: d.delivery,
    method,
    original_sha256: d.original_sha256,
    signature_sha256: sigSha,
    signed_sha256: sha256(outBytes),
    proof: "hmac-sha256 verified",
  };
  try {
    writeFileSync(auditPath, JSON.stringify(audit, null, 2));
  } catch {
    /* ignore */
  }

  d.status = "completed";
  d.applied_at = iso(now);
  d.output_path = outPath;
  d.audit_path = auditPath;
  d.used_proof = got;
  d.signed_pdf_base64 = Buffer.from(outBytes).toString("base64");
  if (d.sealed) {
    d.sealed.abandoned = true;
    d.sealed.key = null;
  }
  d.sign_url = null;
  store(d);

  return {
    request_id: requestId,
    status: "completed",
    output_path: outPath,
    audit_path: auditPath,
    audit,
    signed_pdf_path: outPath,
    signed_pdf_base64: d.signed_pdf_base64,
    signed_pdf_sha256: audit.signed_sha256,
    next: `Attach the signed PDF (${outPath}) back to the signer in the chat right away.`,
  };
}

export async function checkReply(requestId: string): Promise<Record<string, unknown> | null> {
  const d = load(requestId);
  if (d.status !== "pending" || !d.sealed) return null;
  const s = d.sealed;
  const r = getRelay();
  try {
    if (r.exists && !(await r.exists(s.reply_topic))) return null;
    const msgs = await r.fetch(s.reply_topic);
    for (const blob of msgs) {
      try {
        const obj = JSON.parse(unseal(aesKeyFromState(d), Buffer.from(blob), aad("reply", s.reply_topic)).toString("utf8"));
        return await applyResponseObj(requestId, obj);
      } catch {
        continue;
      }
    }
  } catch (e) {
    if (e instanceof SignError) throw e;
    return null;
  }
  return null;
}

export async function sealedStatus(requestId: string, waitSeconds = 0): Promise<Record<string, unknown>> {
  const deadline = Date.now() + Math.max(0, Math.min(waitSeconds || 0, 600)) * 1000;
  let attempt = 0;
  while (true) {
    let d = load(requestId);
    if (d.status === "pending" && new Date(d.expires_at).getTime() < Date.now()) {
      d.status = "expired";
      store(d);
    }
    if (d.status !== "pending") return publicStatus(d);
    const res = await checkReply(requestId);
    if (res && res.status !== "pending") {
      d = load(requestId);
      return publicStatus(d, res);
    }
    if (Date.now() >= deadline) break;
    const delay = Math.min(45_000, 5_000 * Math.pow(1.5, Math.min(attempt, 8)));
    attempt++;
    await new Promise((r) => setTimeout(r, Math.min(delay, Math.max(100, deadline - Date.now()))));
  }
  return publicStatus(load(requestId));
}

function publicStatus(d: RequestState, extra?: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {
    request_id: d.request_id,
    status: d.status,
    delivery: d.delivery,
    created_at: d.created_at,
    expires_at: d.expires_at,
    document_name: d.document_name,
    output_path: d.output_path,
    audit_path: d.audit_path,
  };
  if (d.status === "completed") {
    out.signed_pdf_path = d.output_path;
    if (d.signed_pdf_base64) out.signed_pdf_base64 = d.signed_pdf_base64;
    out.next = `Attach the signed PDF (${d.output_path}) back to the signer in the chat right away.`;
  }
  if (d.status === "pending") {
    out.next =
      `Still pending. Call wait_for_signature(request_id='${d.request_id}', wait_seconds=600) again ` +
      "now, in this same turn, until it is completed/declined/expired/cancelled.";
  }
  if (d.decline_reason) out.decline_reason = d.decline_reason;
  return { ...out, ...extra };
}

export function isSealed(rid: string): boolean {
  try {
    return stateExists(rid) && !!load(rid).sealed;
  } catch {
    return false;
  }
}

export function cancel(rid: string): Record<string, unknown> {
  const d = load(rid);
  if (d.status === "pending") {
    d.status = "cancelled";
    store(d);
  }
  return { request_id: rid, status: d.status };
}
