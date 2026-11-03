import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

// The owner turned the background download off, and images are missing.
const STORAGE = { "grimoire.settings": JSON.stringify({ model: "", askMode: "countdown", autoImages: false }) };
const MISSING = { count: 0, bytes: 0, owned_total: 5, owned_small: 5, owned_normal: 1 };
const STORED = { count: 10, bytes: 1, owned_total: 5, owned_small: 5, owned_normal: 5 };

let app;
let sync;
let status = MISSING;
let prefetchStatus = 200;

function stream(events) {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
}
const DONE = { type: "done", phase: "normal", done: 4, total: 4, failed: 0, skipped: 0 };

before(async () => {
  app = await loadApp({
    storage: STORAGE,
    routes: {
      "GET /api/images/status": () => ({ json: status }),
      "POST /api/images/prefetch": () => (prefetchStatus === 409
        ? { status: 409, json: { detail: "A download is already running." } }
        : { status: 200, body: stream([DONE]), headers: { "content-type": "text/event-stream" } }),
    },
  });
  sync = await import("../../../frontend/js/shared/imagesync.js");
});

const posts = () => app.fetchLog.filter((r) => r.method === "POST" && r.path === "/api/images/prefetch").length;

function setup({ auto, images, code = 200 }) {
  window_storage(auto);
  status = images;
  prefetchStatus = code;
  app.fetchLog.length = 0;
}
function window_storage(auto) {
  app.window.localStorage.setItem("grimoire.settings", JSON.stringify({ model: "", askMode: "countdown", autoImages: auto }));
}

test("main does not start a download when autoImages is off", async () => {
  // The boot ran with autoImages off and missing images. No request went out.
  assert.equal(app.fetchLog.filter((r) => r.path === "/api/images/prefetch").length, 0);
  assert.equal(sync.imageSyncState().running, false);
});

test("the start-up sync does not start when autoImages is off", async () => {
  setup({ auto: false, images: MISSING });
  await sync.autoStartImageSync();
  assert.equal(posts(), 0);
});

test("the start-up sync does not start when every image is stored", async () => {
  setup({ auto: true, images: STORED });
  await sync.autoStartImageSync();
  assert.equal(posts(), 0);
});

test("the start-up sync does not start when no card is owned", async () => {
  setup({ auto: true, images: { count: 0, bytes: 0, owned_total: 0, owned_small: 0, owned_normal: 0 } });
  await sync.autoStartImageSync();
  assert.equal(posts(), 0);
});

test("the start-up sync starts a quiet run when images are missing", async () => {
  setup({ auto: true, images: MISSING });
  document_toasts_clear();
  await sync.autoStartImageSync();
  assert.equal(posts(), 1);
  assert.deepEqual(sync.imageSyncState(), {
    running: false, phase: "normal", done: 4, total: 4, failed: 0, skipped: 0, error: null,
  });
  assert.equal(app.document.querySelectorAll("#toast-container .toast").length, 0);
});

test("the start-up sync ignores a 409 without a toast", async () => {
  setup({ auto: true, images: MISSING, code: 409 });
  document_toasts_clear();
  await sync.autoStartImageSync();
  assert.equal(sync.imageSyncState().error, "busy");
  assert.equal(app.document.querySelectorAll("#toast-container .toast").length, 0);
});

test("subscribers hear each change and can unsubscribe", async () => {
  setup({ auto: true, images: MISSING });
  const seen = [];
  const off = sync.onImageSync((state) => seen.push(state.running));
  await sync.startImageSync();
  assert.deepEqual(seen.slice(0, 1), [true]);
  assert.equal(seen[seen.length - 1], false);
  const count = seen.length;
  off();
  await sync.startImageSync();
  assert.equal(seen.length, count);
});

function document_toasts_clear() {
  app.document.getElementById("toast-container").textContent = "";
}
