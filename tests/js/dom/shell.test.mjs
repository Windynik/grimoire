import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;

before(async () => {
  app = await loadApp({
    reducedMotion: true,
    // There is no collection: the owner skipped the welcome screen, so Home shows.
    storage: { welcomeSkipped: "1" },
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "missing" } }),
      "GET /api/collections": () => ({ json: { collections: [] } }),
    },
  });
});

test("reduced motion builds no motes", () => {
  assert.ok(app.document.querySelector(".atmosphere"));
  assert.equal(app.document.querySelectorAll(".atmosphere .mote").length, 0);
});

test("reduced motion still opens Home", () => {
  assert.ok(app.document.getElementById("home-view").classList.contains("active"));
});
