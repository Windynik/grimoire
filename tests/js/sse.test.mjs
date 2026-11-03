import { test } from "node:test";
import assert from "node:assert/strict";
import { readSSE } from "../../frontend/js/shared/sse.js";

function streamOf(chunks) {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
}

test("readSSE parses split chunks", async () => {
  const body = streamOf(['data: {"a":1}\n', '\ndata: {"b"', ':2}\n\n']);
  const seen = [];
  await readSSE(new Response(body), (e) => seen.push(e));
  assert.deepEqual(seen, [{ a: 1 }, { b: 2 }]);
});

test("readSSE skips a bad line and keeps going", async () => {
  const warn = console.warn;
  const warnings = [];
  console.warn = (...args) => warnings.push(args);
  try {
    const seen = [];
    await readSSE(new Response(streamOf(['data: nope\n\ndata: {"c":3}\n\n'])), (e) => seen.push(e));
    assert.deepEqual(seen, [{ c: 3 }]);
    assert.equal(warnings.length, 1);
  } finally {
    console.warn = warn;
  }
});

test("readSSE ignores lines that are not data lines", async () => {
  const seen = [];
  await readSSE(new Response(streamOf([': ping\n\nevent: x\ndata: {"d":4}\n\n'])), (e) => seen.push(e));
  assert.deepEqual(seen, [{ d: 4 }]);
});
