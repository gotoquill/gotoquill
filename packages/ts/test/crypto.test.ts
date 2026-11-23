import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { aad, seal, unseal, newKey, newTopic, hmacSha256Hex, proofMessage, b64u, b64uDecode } from "../src/crypto.js";

describe("crypto", () => {
  it("seal/unseal roundtrip", () => {
    const key = newKey();
    const topic = newTopic();
    const pt = Buffer.from(JSON.stringify({ hello: "world" }));
    const blob = seal(key, pt, aad("request", topic));
    const out = unseal(key, blob, aad("request", topic));
    assert.equal(out.toString(), pt.toString());
  });

  it("aad mismatch fails", () => {
    const key = newKey();
    const blob = seal(key, Buffer.from("x"), aad("request", "topicA"));
    assert.throws(() => unseal(key, blob, aad("request", "topicB")));
  });

  it("b64u roundtrip", () => {
    const b = Buffer.from([1, 2, 3, 250]);
    assert.deepEqual(b64uDecode(b64u(b)), b);
  });

  it("hmac proof message", () => {
    const key = Buffer.alloc(32, 7);
    const msg = proofMessage("req_1", "doc", "sig", "drawn", "", "Ada", "2026-01-01T00:00:00Z");
    const h = hmacSha256Hex(key, msg);
    assert.equal(h.length, 64);
  });
});
