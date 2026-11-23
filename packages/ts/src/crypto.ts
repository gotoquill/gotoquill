/**
 * AES-256-GCM sealed-link crypto. Wire format matches Python gotoquill.relay:
 * blob = iv(12) || ciphertext||tag; AAD = "gotoquill/sealed/v1|{kind}|{topic}".
 */
import { createCipheriv, createDecipheriv, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

export function aad(kind: string, topic: string): Buffer {
  return Buffer.from(`gotoquill/sealed/v1|${kind}|${topic}`, "utf8");
}

export function seal(key: Buffer, plaintext: Buffer, ad: Buffer): Buffer {
  if (key.length !== 32) throw new Error("key must be 32 bytes");
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(ad);
  const enc = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([iv, enc, tag]);
}

export function unseal(key: Buffer, blob: Buffer, ad: Buffer): Buffer {
  if (blob.length < 12 + 16) throw new Error("ciphertext too short");
  const iv = blob.subarray(0, 12);
  const tag = blob.subarray(blob.length - 16);
  const data = blob.subarray(12, blob.length - 16);
  const decipher = createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAAD(ad);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(data), decipher.final()]);
}

export function b64u(buf: Buffer): string {
  return buf.toString("base64url");
}

export function b64uDecode(s: string): Buffer {
  return Buffer.from(s, "base64url");
}

export function proofMessage(
  rid: string,
  docSha: string,
  sigSha: string,
  method: string,
  typedName: string,
  signerName: string,
  clientTs: string,
): string {
  return ["gotoquill/v1", rid, docSha, sigSha, method || "", typedName || "", signerName || "", clientTs || ""].join("|");
}

export function hmacSha256Hex(key: Buffer, message: string): string {
  return createHmac("sha256", key).update(message, "utf8").digest("hex");
}

export function safeEqualHex(a: string, b: string): boolean {
  try {
    const ba = Buffer.from(a, "hex");
    const bb = Buffer.from(b, "hex");
    if (ba.length !== bb.length || ba.length === 0) return false;
    return timingSafeEqual(ba, bb);
  } catch {
    return false;
  }
}

export function newKey(): Buffer {
  return randomBytes(32);
}

export function newTopic(): string {
  return randomBytes(32).toString("base64url");
}

export function newRequestId(): string {
  return "req_" + randomBytes(8).toString("hex");
}
