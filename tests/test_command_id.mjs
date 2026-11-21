import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import test from "node:test";

import { newCommandId } from '../app/static/command-id.js';
const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

test("usa il metodo nativo quando disponibile, con il receiver corretto", () => {
  const api = { randomUUID() { assert.equal(this, api); return "native-result"; } };
  assert.equal(newCommandId(api), "native-result");
});

test("senza randomUUID imposta versione e variante anche con tutti i bit a uno", () => {
  const api = { getRandomValues(bytes) { assert.equal(this, api); return bytes.fill(255); } };
  assert.equal(newCommandId(api), "ffffffff-ffff-4fff-bfff-ffffffffffff");
});

test("su HTTP usa getRandomValues senza perdere formato o unicità dei comandi", () => {
  const api = { getRandomValues: bytes => webcrypto.getRandomValues(bytes) };
  const ids = Array.from({ length: 1000 }, () => newCommandId(api));
  assert.equal(new Set(ids).size, ids.length);
  for (const id of ids) assert.match(id, uuidV4);
});

test("assenza di casualità sicura segnalata senza ripiegare su Math.random", () => {
  for (const api of [null, {}]) assert.throws(() => newCommandId(api), /browser aggiornato/);
});
